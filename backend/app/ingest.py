"""Reddit crawler: fill the vector store with a community's voices.

    python -m app.ingest gaming                # month backfill (~200 posts)
    python -m app.ingest gaming --window week  # trailing week only

Flow: listing sweep (paginated top.json) -> parallel comment fetches ->
post markdown -> chunk -> embed (batched) -> sqlite-vec index -> PCA.
Idempotent: posts upsert by id and chunk IDs are content-stable, so re-runs
and overlapping windows only add what's new.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from app import config, db
from app.rag.chunker import chunk_markdown
from app.rag.embeddings import EmbeddingProvider, VoyageEmbeddingProvider
from app.rag.pca import compute_pca
from app.rag.vector_index import VectorIndex

LISTING_PAGES = 2          # 2 x limit=100 -> ~200 posts for the month sweep
COMMENTS_PER_POST = 12
MIN_COMMENTS_TO_FETCH = 10  # skip comment requests for low-discussion posts
TOP_POSTS_PER_WEEK = 30     # only the week's top posts get comment fetches
SELFTEXT_MAX_CHARS = 2000
COMMENT_MAX_CHARS = 800
EMBED_BATCH = 64
FETCH_WORKERS = 6


def make_session() -> requests.Session:
    """Session for Reddit. With REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET set
    (free "script app" from reddit.com/prefs/apps), uses app-only OAuth
    against oauth.reddit.com — reliable everywhere. Without them, falls back
    to the public .json endpoints, which Reddit blocks on many networks."""
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    session.base = "https://www.reddit.com"
    if client_id and client_secret:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            headers={"User-Agent": config.USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        session.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        session.base = "https://oauth.reddit.com"
    return session


def _get(session: requests.Session, path: str, **params) -> dict:
    """GET with one retry on rate-limit/server errors."""
    for attempt in (0, 1):
        resp = session.get(
            f"{session.base}{path}", params={**params, "raw_json": 1}, timeout=30
        )
        if resp.status_code in (429, 500, 502, 503) and attempt == 0:
            time.sleep(10)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("unreachable")  # pragma: no cover


def fetch_top_posts(
    session: requests.Session, subreddit: str, window: str, pages: int
) -> list[dict]:
    posts: list[dict] = []
    after: str | None = None
    for _ in range(pages):
        payload = _get(
            session,
            f"/r/{subreddit}/top.json",
            t=window,
            limit=100,
            **({"after": after} if after else {}),
        )
        children = payload["data"]["children"]
        posts.extend(c["data"] for c in children if c["kind"] == "t3")
        after = payload["data"].get("after")
        if not after:
            break
    return posts


def fetch_comments(session: requests.Session, permalink: str) -> list[dict]:
    """Top-level comments only, skipping bots/stickied/deleted."""
    try:
        payload = _get(
            session,
            f"{permalink.rstrip('/')}.json",
            sort="top",
            limit=COMMENTS_PER_POST * 2,
            depth=1,
        )
    except Exception:
        return []  # a failed comment fetch never sinks the ingest
    out: list[dict] = []
    for child in payload[1]["data"]["children"]:
        if child.get("kind") != "t1":
            continue
        c = child["data"]
        if (
            c.get("stickied")
            or c.get("author") in (None, "AutoModerator", "[deleted]")
            or c.get("body") in (None, "[deleted]", "[removed]")
        ):
            continue
        out.append(c)
        if len(out) >= COMMENTS_PER_POST:
            break
    return out


def select_for_comments(posts: list[dict]) -> list[dict]:
    """Top posts per trailing 7-day bucket with enough discussion to fetch."""
    if not posts:
        return []
    newest = max(p["created_utc"] for p in posts)
    buckets: dict[int, list[dict]] = {}
    for p in posts:
        buckets.setdefault(int((newest - p["created_utc"]) // (7 * 86400)), []).append(p)
    selected: list[dict] = []
    for bucket in buckets.values():
        bucket.sort(key=lambda p: p.get("score", 0), reverse=True)
        selected.extend(
            p
            for p in bucket[:TOP_POSTS_PER_WEEK]
            if p.get("num_comments", 0) >= MIN_COMMENTS_TO_FETCH
        )
    return selected


def post_to_markdown(post: dict, comments: list[dict]) -> str:
    created = datetime.fromtimestamp(post["created_utc"], tz=timezone.utc).date()
    flair = post.get("link_flair_text")
    meta = (
        f"{post.get('score', 0)} points · {post.get('num_comments', 0)} comments · "
        f"u/{post.get('author', '?')} · {created}"
        + (f" · flair: {flair}" if flair else "")
    )
    lines = [f"# {post['title']}", meta, ""]
    selftext = (post.get("selftext") or "").strip()
    if selftext:
        lines += [selftext[:SELFTEXT_MAX_CHARS], ""]
    if comments:
        lines.append("## Top comments")
        for c in comments:
            body = " ".join(c["body"].split())[:COMMENT_MAX_CHARS]
            lines.append(f"- u/{c['author']} ({c.get('score', 0)} pts): {body}")
    return "\n".join(lines)


def ingest_posts(
    conn: sqlite3.Connection,
    subreddit: str,
    posts: list[dict],
    comments_by_id: dict[str, list[dict]],
    provider: EmbeddingProvider,
    vector_index: VectorIndex,
) -> dict:
    """Shared upsert -> chunk -> embed -> index path (CLI and live pull)."""
    with conn:
        conn.executemany(
            "INSERT INTO posts(id, title, author, score, num_comments, "
            "  created_utc, permalink, flair) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET score = excluded.score, "
            "  num_comments = excluded.num_comments, flair = excluded.flair",
            [
                (
                    p["name"],
                    p["title"],
                    p.get("author"),
                    p.get("score", 0),
                    p.get("num_comments", 0),
                    p["created_utc"],
                    p.get("permalink"),
                    p.get("link_flair_text"),
                )
                for p in posts
            ],
        )

    chunks = []
    for p in posts:
        md = post_to_markdown(p, comments_by_id.get(p["name"], []))
        chunks.extend(chunk_markdown(p["name"], md))

    # Skip chunks already embedded (stable IDs make re-runs surgical).
    existing = {
        row["chunk_id"]
        for row in conn.execute("SELECT chunk_id FROM chunks").fetchall()
    }
    new_chunks = [c for c in chunks if c.chunk_id not in existing]

    for i in range(0, len(new_chunks), EMBED_BATCH):
        batch = new_chunks[i : i + EMBED_BATCH]
        vectors = provider.embed_documents([c.content for c in batch])
        vector_index.add_documents(zip(batch, vectors))

    if new_chunks:
        payload = compute_pca(
            vector_index, model=provider.model, dim=provider.dim
        )
        if payload:
            db.set_meta(conn, "pca", json.dumps(payload))

    db.set_meta(conn, "subreddit", subreddit)
    db.set_meta(conn, "embedding_model", provider.model)
    db.set_meta(conn, "embedding_dim", str(provider.dim))
    db.set_meta(
        conn,
        "ingested_at",
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return {
        "posts": len(posts),
        "chunks_total": len(chunks),
        "chunks_new": len(new_chunks),
    }


def run_ingest(
    conn: sqlite3.Connection,
    vector_index: VectorIndex,
    provider: EmbeddingProvider,
    subreddit: str,
    window: str = "month",
    pages: int = LISTING_PAGES,
) -> dict:
    session = make_session()

    t0 = time.perf_counter()
    posts = fetch_top_posts(session, subreddit, window, pages)
    wanting_comments = select_for_comments(posts)
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        fetched = pool.map(
            lambda p: (p["name"], fetch_comments(session, p["permalink"])),
            wanting_comments,
        )
        comments_by_id = dict(fetched)
    fetch_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    report = ingest_posts(
        conn, subreddit, posts, comments_by_id, provider, vector_index
    )
    report.update(
        {
            "comment_fetches": len(wanting_comments),
            "fetch_s": round(fetch_s, 1),
            "index_s": round(time.perf_counter() - t0, 1),
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a subreddit's voices")
    parser.add_argument("subreddit", nargs="?", default=config.DEFAULT_SUBREDDIT)
    parser.add_argument("--window", choices=["month", "week"], default="month")
    parser.add_argument("--pages", type=int, default=LISTING_PAGES,
                        help="listing pages of 100 posts each")
    args = parser.parse_args()

    conn = db.connect(config.DB_PATH)
    vector_index = VectorIndex(config.DB_PATH, dim=config.EMBEDDING_DIM)
    provider = VoyageEmbeddingProvider(model=config.EMBEDDING_MODEL)
    report = run_ingest(
        conn, vector_index, provider, args.subreddit,
        window=args.window, pages=args.pages,
    )
    print(json.dumps(report, indent=2))
    for w in db.week_windows(conn):
        print(f"  week {w['week_start']}: {w['n_posts']} posts, {w['n_chunks']} chunks")


if __name__ == "__main__":
    sys.exit(main())

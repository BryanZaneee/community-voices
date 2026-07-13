"""Community crawler: fill the vector store with a community's voices.

Two sources share one pipeline, both keyless/no-approval-needed:
- lemmy (default): the open Lemmy API.
    python -m app.ingest games --window month
- hackernews: Algolia's HN Search API.
    python -m app.ingest --source hackernews --window month

Flow: listing sweep (paginated) -> parallel comment fetches -> post markdown
-> chunk -> embed (batched) -> sqlite-vec index -> 2-D projection.
Idempotent: posts upsert by id and chunk IDs hash position + content, so
re-runs and overlapping windows only embed what's new or edited, and
superseded chunks of re-crawled posts are pruned.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from app import config, db
from app.rag.chunker import chunk_markdown
from app.rag.embeddings import EmbeddingProvider, VoyageEmbeddingProvider
from app.rag.pca import compute_pca
from app.rag.vector_index import VectorIndex

LISTING_PAGES = 2          # 2 x limit=100 -> ~200 posts for the month sweep
COMMENTS_PER_POST = 12
MIN_COMMENTS_TO_FETCH = 5  # skip comment requests for low-discussion posts
TOP_POSTS_PER_WEEK = 30     # only the week's top posts get comment fetches
SELFTEXT_MAX_CHARS = 2000
COMMENT_MAX_CHARS = 800
EMBED_BATCH = 64
FETCH_WORKERS = 6


def _get_json(session: requests.Session, url: str, **params) -> dict:
    """GET with one retry on rate-limit/server errors."""
    for attempt in (0, 1):
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code in (429, 500, 502, 503) and attempt == 0:
            time.sleep(10)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------- lemmy ----

LEMMY_INSTANCE = "https://lemmy.world"


def _lemmy_post_to_common(pv: dict) -> dict:
    """Flatten a Lemmy post_view onto the dict shape the pipeline uses."""
    post, counts = pv["post"], pv["counts"]
    created = datetime.fromisoformat(post["published"].replace("Z", "+00:00"))
    return {
        "name": f"lemmy_{post['id']}",
        "_lemmy_id": post["id"],
        "title": post["name"],
        "author": pv["creator"]["name"],
        "score": counts["score"],
        "num_comments": counts["comments"],
        "created_utc": created.timestamp(),
        "permalink": post.get("ap_id"),
        "link_flair_text": None,
        "selftext": post.get("body") or "",
    }


def fetch_top_posts_lemmy(
    session: requests.Session, community: str, window: str, pages: int
) -> list[dict]:
    sort = "TopMonth" if window == "month" else "TopWeek"
    posts: list[dict] = []
    for page in range(1, pages + 1):
        payload = _get_json(
            session,
            f"{LEMMY_INSTANCE}/api/v3/post/list",
            community_name=community,
            sort=sort,
            limit=50,
            page=page,
        )
        batch = payload.get("posts", [])
        posts.extend(_lemmy_post_to_common(pv) for pv in batch)
        if len(batch) < 50:
            break
    return posts


def fetch_comments_lemmy(session: requests.Session, post: dict) -> list[dict]:
    """Top-level comments (author/score/body), bots and deleted skipped."""
    try:
        payload = _get_json(
            session,
            f"{LEMMY_INSTANCE}/api/v3/comment/list",
            post_id=post["_lemmy_id"],
            sort="Top",
            limit=COMMENTS_PER_POST * 2,
            max_depth=1,
        )
    except Exception:
        return []
    out = []
    for cv in payload.get("comments", []):
        body = (cv["comment"].get("content") or "").strip()
        if not body or cv["comment"].get("deleted") or cv["comment"].get("removed"):
            continue
        out.append(
            {
                "author": cv["creator"]["name"],
                "score": cv["counts"]["score"],
                "body": body,
            }
        )
        if len(out) >= COMMENTS_PER_POST:
            break
    return out


# ----------------------------------------------------------- hackernews ----

HN_API = "https://hn.algolia.com/api/v1"


def _hn_strip_html(text: str) -> str:
    """HN comment/story text is HTML (<p>, <a href>, entities) — plain text
    is all the pipeline needs."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def _hn_hit_to_common(hit: dict) -> dict:
    """Map an Algolia HN search hit onto the dict shape the pipeline uses."""
    return {
        "name": f"hn_{hit['objectID']}",
        "_hn_id": hit["objectID"],
        "title": hit.get("title") or "(untitled)",
        "author": hit.get("author"),
        "score": hit.get("points") or 0,
        "num_comments": hit.get("num_comments") or 0,
        "created_utc": hit["created_at_i"],
        "permalink": f"https://news.ycombinator.com/item?id={hit['objectID']}",
        "link_flair_text": None,
        "selftext": "",  # search hits don't carry story text; most are links
    }


def fetch_top_posts_hn(
    session: requests.Session, window: str, pages: int
) -> list[dict]:
    days = 30 if window == "month" else 7
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    posts: list[dict] = []
    for page in range(pages):
        payload = _get_json(
            session,
            f"{HN_API}/search_by_date",
            tags="story",
            numericFilters=f"created_at_i>{cutoff}",
            hitsPerPage=100,
            page=page,
        )
        hits = payload.get("hits", [])
        posts.extend(_hn_hit_to_common(h) for h in hits)
        if len(hits) < 100:
            break
    return posts


def fetch_comments_hn(session: requests.Session, post: dict) -> list[dict]:
    """Top-level comments, in HN's own ranking order (no per-comment score)."""
    try:
        payload = _get_json(session, f"{HN_API}/items/{post['_hn_id']}")
    except Exception:
        return []
    out = []
    for child in payload.get("children") or []:
        text = child.get("text")
        if not text:
            continue  # deleted/dead
        out.append(
            {
                "author": child.get("author") or "?",
                "score": child.get("points") or 0,
                "body": _hn_strip_html(text),
            }
        )
        if len(out) >= COMMENTS_PER_POST:
            break
    return out


# --------------------------------------------------------------- shared ----


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

    # Content is part of the chunk ID, so an edited post (score/comment
    # counts drift between crawls) yields new IDs. Prune the superseded rows
    # for this run's posts before the skip-existing filter, or every re-crawl
    # would pile up near-duplicate chunks.
    if posts:
        new_ids = {c.chunk_id for c in chunks}
        ph = ",".join("?" * len(posts))
        stale = [
            row["chunk_id"]
            for row in conn.execute(
                f"SELECT chunk_id FROM chunks WHERE path IN ({ph})",
                [p["name"] for p in posts],
            )
            if row["chunk_id"] not in new_ids
        ]
        if stale:
            vector_index.delete_chunks(stale)
            with conn:
                conn.executemany(
                    "DELETE FROM retrieval_stats WHERE chunk_id = ?",
                    [(cid,) for cid in stale],
                )

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
    community: str,
    window: str = "month",
    pages: int = LISTING_PAGES,
    source: str = "lemmy",
) -> dict:
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT

    if source == "hackernews":
        display_name = "Hacker News"
        fetch_posts = lambda: fetch_top_posts_hn(session, window, pages)
        fetch_one = fetch_comments_hn
    else:
        display_name = f"{community}@{LEMMY_INSTANCE.removeprefix('https://')}"
        fetch_posts = lambda: fetch_top_posts_lemmy(session, community, window, pages * 2)
        fetch_one = fetch_comments_lemmy

    t0 = time.perf_counter()
    posts = fetch_posts()
    wanting_comments = select_for_comments(posts)
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        fetched = pool.map(
            lambda p: (p["name"], fetch_one(session, p)),
            wanting_comments,
        )
        comments_by_id = dict(fetched)
    fetch_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    report = ingest_posts(
        conn, display_name, posts, comments_by_id, provider, vector_index
    )
    db.set_meta(conn, "source", source)
    report.update(
        {
            "comments": sum(len(v) for v in comments_by_id.values()),
            "comment_fetches": len(wanting_comments),
            "fetch_s": round(fetch_s, 1),
            "index_s": round(time.perf_counter() - t0, 1),
        }
    )
    # The ingestion tab's funnel/latest-run card reads this back after restart.
    db.set_meta(conn, "ingest_report", json.dumps(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a community's voices")
    parser.add_argument("community", nargs="?", default=config.DEFAULT_COMMUNITY)
    parser.add_argument("--source", choices=["lemmy", "hackernews"], default="lemmy")
    parser.add_argument("--window", choices=["month", "week"], default="month")
    parser.add_argument("--pages", type=int, default=LISTING_PAGES,
                        help="listing pages (~100 posts each)")
    args = parser.parse_args()

    conn = db.connect(config.DB_PATH)
    vector_index = VectorIndex(config.DB_PATH, dim=config.EMBEDDING_DIM)
    provider = VoyageEmbeddingProvider(model=config.EMBEDDING_MODEL)
    report = run_ingest(
        conn, vector_index, provider, args.community,
        window=args.window, pages=args.pages, source=args.source,
    )
    print(json.dumps(report, indent=2))
    for w in db.week_windows(conn):
        print(f"  week {w['week_start']}: {w['n_posts']} posts, {w['n_chunks']} chunks")


if __name__ == "__main__":
    main()

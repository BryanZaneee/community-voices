"""Community crawler: fill the vector store with a community's voices.

Three sources share one pipeline:
- lemmy (default): the open Lemmy API, keyless.
    python -m app.ingest games --window month
- hackernews: Algolia's HN Search API, keyless.
    python -m app.ingest --source hackernews --window month
- reddit: top.json listings, best effort without credentials and reliable
  with a free script app (see reddit_session and README).
    python -m app.ingest games --source reddit --window month

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
import os
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

LISTING_PAGES = 2          # ~200-post month sweep (volume cap)
COMMENTS_PER_POST = 12
MIN_COMMENTS_TO_FETCH = 5  # skip quiet threads
TOP_POSTS_PER_WEEK = 30     # only top posts get comment fetches
SELFTEXT_MAX_CHARS = 2000
COMMENT_MAX_CHARS = 800
EMBED_BATCH = 64
FETCH_WORKERS = 6


def _get_json(session: requests.Session, url: str, **params) -> dict | list:
    """GET with one retry (after a 10 s sleep) on 429 or 5xx."""
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
    # Paginated Lemmy /api/v3/post/list (TopMonth or TopWeek).
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


# --------------------------------------------------------------- reddit ----

REDDIT_PUBLIC = "https://www.reddit.com"
REDDIT_OAUTH = "https://oauth.reddit.com"


def reddit_session(session: requests.Session) -> requests.Session:
    """Point `session` at Reddit, with app-only OAuth when credentials exist.

    Reddit's Data API gate blocks unauthenticated .json on most networks, so
    the public base is a best effort. REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET
    from a free script app (reddit.com/prefs/apps) switch it to
    oauth.reddit.com, which is reliable. REDDIT_USER_AGENT overrides the
    default crawler User-Agent; Reddit rejects generic ones.
    """
    session.base = REDDIT_PUBLIC
    session.headers["User-Agent"] = os.environ.get(
        "REDDIT_USER_AGENT", config.USER_AGENT
    )
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (client_id and client_secret):
        return session
    resp = session.post(
        f"{REDDIT_PUBLIC}/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=30,
    )
    resp.raise_for_status()
    session.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    session.base = REDDIT_OAUTH
    return session


def _reddit_to_common(child: dict) -> dict:
    """Flatten a Reddit t3 listing child onto the dict shape the pipeline uses."""
    d = child["data"]
    return {
        "name": f"reddit_{d['id']}",
        "_reddit_permalink": d["permalink"],
        "title": d.get("title") or "(untitled)",
        "author": d.get("author"),
        "score": d.get("score") or 0,
        "num_comments": d.get("num_comments") or 0,
        "created_utc": d["created_utc"],
        "permalink": f"{REDDIT_PUBLIC}{d['permalink']}",
        "link_flair_text": d.get("link_flair_text"),
        "selftext": d.get("selftext") or "",
    }


def fetch_top_posts_reddit(
    session: requests.Session, subreddit: str, window: str, pages: int
) -> list[dict]:
    # Paginated /r/<sub>/top.json, 100 per page, cursor in data.after.
    base = getattr(session, "base", REDDIT_PUBLIC)
    posts: list[dict] = []
    after: str | None = None
    for _ in range(pages):
        payload = _get_json(
            session,
            f"{base}/r/{subreddit}/top.json",
            t="month" if window == "month" else "week",
            limit=100,
            raw_json=1,
            **({"after": after} if after else {}),
        )
        data = payload.get("data") or {} if isinstance(payload, dict) else {}
        children = [c for c in data.get("children", []) if c.get("kind") == "t3"]
        posts.extend(_reddit_to_common(c) for c in children)
        after = data.get("after")
        if not after:
            break
    return posts


def fetch_comments_reddit(session: requests.Session, post: dict) -> list[dict]:
    """Top-level comments, skipping stickied, bot, and deleted entries."""
    base = getattr(session, "base", REDDIT_PUBLIC)
    try:
        payload = _get_json(
            session,
            f"{base}{post['_reddit_permalink'].rstrip('/')}.json",
            sort="top",
            limit=COMMENTS_PER_POST * 2,
            depth=1,
            raw_json=1,
        )
    except Exception:
        return []  # a failed comment fetch never sinks the ingest
    # The comments endpoint returns [post listing, comment listing].
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    out = []
    for child in payload[1].get("data", {}).get("children", []):
        if child.get("kind") != "t1":
            continue
        c = child["data"]
        body = (c.get("body") or "").strip()
        author = c.get("author")
        if (
            not body
            or body in ("[deleted]", "[removed]")
            or c.get("stickied")
            or author in (None, "AutoModerator", "[deleted]")
        ):
            continue
        out.append({"author": author, "score": c.get("score") or 0, "body": body})
        if len(out) >= COMMENTS_PER_POST:
            break
    return out


# --------------------------------------------------------------- shared ----


def select_for_comments(posts: list[dict]) -> list[dict]:
    """Volume control: top N posts per week bucket with enough discussion."""
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
    # One post → markdown doc the chunker will split (title / body / comments).
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
    community: str,
    posts: list[dict],
    comments_by_id: dict[str, list[dict]],
    provider: EmbeddingProvider,
    vector_index: VectorIndex,
) -> dict:
    """Upsert posts → markdown → chunk → embed new IDs → sqlite-vec (+ PCA)."""
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
            vector_index.delete_chunks(stale)  # also drops retrieval_stats

    # Skip chunks already embedded (stable IDs make re-runs surgical).
    existing = {
        row["chunk_id"]
        for row in conn.execute("SELECT chunk_id FROM chunks").fetchall()
    }
    new_chunks = [c for c in chunks if c.chunk_id not in existing]

    for i in range(0, len(new_chunks), EMBED_BATCH):
        # Voyage batches of 64; only brand-new chunk IDs hit the API.
        batch = new_chunks[i : i + EMBED_BATCH]
        vectors = provider.embed_documents([c.content for c in batch])
        vector_index.add_documents(zip(batch, vectors))

    if new_chunks:
        # Refresh 2-D map coords for the Embeddings tab.
        payload = compute_pca(
            vector_index, model=provider.model, dim=provider.dim
        )
        if payload:
            db.set_meta(conn, "pca", json.dumps(payload))

    db.set_meta(conn, "community", community)
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
    reset: bool = False,
) -> dict:
    """Full crawl pipeline: fetch posts/comments → ingest_posts. CLI + live pull."""
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT

    if source == "hackernews":
        display_name = "Hacker News"
        fetch_posts = lambda: fetch_top_posts_hn(session, window, pages)
        fetch_one = fetch_comments_hn
    elif source == "reddit":
        display_name = f"r/{community}"
        reddit_session(session)
        fetch_posts = lambda: fetch_top_posts_reddit(session, community, window, pages)
        fetch_one = fetch_comments_reddit
    else:
        display_name = f"{community}@{LEMMY_INSTANCE.removeprefix('https://')}"
        fetch_posts = lambda: fetch_top_posts_lemmy(session, community, window, pages * 2)
        fetch_one = fetch_comments_lemmy

    t0 = time.perf_counter()
    posts = fetch_posts()
    wanting_comments = select_for_comments(posts)
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        # Parallel comment fetches (volume-capped set only).
        fetched = pool.map(
            lambda p: (p["name"], fetch_one(session, p)),
            wanting_comments,
        )
        comments_by_id = dict(fetched)
    fetch_s = time.perf_counter() - t0

    # reset=True wipes the previous dataset only after the crawl succeeded,
    # so a network failure (or an empty listing) can't leave the DB empty.
    if reset:
        if not posts:
            raise RuntimeError(f"crawl returned no posts for {display_name}")
        db.reset_dataset(conn)

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
    parser.add_argument("--source", choices=["lemmy", "hackernews", "reddit"], default="lemmy")
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

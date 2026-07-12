"""Shared sqlite connection, app schema, and small helpers.

The vec_chunks / chunks tables are owned by app.rag.vector_index (its DDL is
additive CREATE IF NOT EXISTS, so both layers coexist in one file).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.rag.bm25_index import BM25Index
from app.rag.vector_index import VectorIndex, _load_sqlite_vec

SCHEMA = """
-- Same DDL as app.rag.vector_index (CREATE IF NOT EXISTS on both sides), so
-- the schema is complete even before the first embedding is written.
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  rowid INTEGER NOT NULL UNIQUE,
  path TEXT NOT NULL,
  heading_path TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  content TEXT NOT NULL,
  tokens_est INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);

CREATE TABLE IF NOT EXISTS posts (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT,
  score INTEGER,
  num_comments INTEGER,
  created_utc REAL NOT NULL,
  permalink TEXT,
  flair TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_utc);

CREATE TABLE IF NOT EXISTS retrieval_stats (
  chunk_id TEXT PRIMARY KEY,
  retrieved_count INTEGER NOT NULL DEFAULT 0,
  last_retrieved_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  mode TEXT NOT NULL CHECK (mode IN ('rag','baseline')),
  model_key TEXT NOT NULL,
  week_start TEXT NOT NULL,
  subreddit TEXT NOT NULL,
  content_md TEXT NOT NULL,
  report_json TEXT,
  queries TEXT,
  retrieved_chunk_ids TEXT,
  retrieval_mode TEXT CHECK (retrieval_mode IN ('hybrid','vector','bm25')),
  latency_ms INTEGER,
  input_tokens INTEGER,
  output_tokens INTEGER
);

CREATE TABLE IF NOT EXISTS comparisons (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  kind TEXT NOT NULL CHECK (
    kind IN ('rag_vs_baseline','model_vs_model','retrieval_vs_retrieval')),
  doc_a_id INTEGER NOT NULL REFERENCES documents(id),
  doc_b_id INTEGER NOT NULL REFERENCES documents(id),
  judge_json TEXT,
  extra_json TEXT
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _load_sqlite_vec(conn)  # so joins against vec_chunks work on this conn too
    conn.executescript(SCHEMA)
    # Migrate DBs created before report_json existed (CREATE IF NOT EXISTS
    # above is a no-op for them).
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    if "report_json" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN report_json TEXT")
    conn.commit()
    return conn


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def bump_stats(conn: sqlite3.Connection, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        conn.executemany(
            "INSERT INTO retrieval_stats(chunk_id, retrieved_count, last_retrieved_at) "
            "VALUES (?, 1, ?) "
            "ON CONFLICT(chunk_id) DO UPDATE SET "
            "  retrieved_count = retrieved_count + 1, "
            "  last_retrieved_at = excluded.last_retrieved_at",
            [(cid, now) for cid in chunk_ids],
        )


def build_bm25(conn: sqlite3.Connection) -> BM25Index:
    """Rebuild the in-memory BM25 index from the chunks table (ms at our scale)."""
    idx = BM25Index()
    for row in conn.execute(
        "SELECT chunk_id, path, heading_path, start_line, end_line, "
        "content, tokens_est FROM chunks"
    ):
        idx.add(VectorIndex._chunk_from_row(row))
    return idx


def week_windows(conn: sqlite3.Connection) -> list[dict]:
    """Available [week_start, week_start+7d) windows, newest first, derived
    from actual post coverage: trailing 7-day windows anchored at the newest
    post, extended back while windows still contain posts."""
    row = conn.execute(
        "SELECT MIN(created_utc) AS lo, MAX(created_utc) AS hi FROM posts"
    ).fetchone()
    if row["hi"] is None:
        return []
    newest = datetime.fromtimestamp(row["hi"], tz=timezone.utc)
    oldest = datetime.fromtimestamp(row["lo"], tz=timezone.utc)
    windows = []
    # Midnight-aligned boundaries so week_start (an ISO date) identifies the
    # window exactly — posts_in_week() recomputes the same [start, start+7d).
    end = (newest + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    while end > oldest:
        start = end - timedelta(days=7)
        stats = conn.execute(
            "SELECT COUNT(*) AS n_posts, "
            "  (SELECT COUNT(*) FROM chunks c JOIN posts p2 ON c.path = p2.id "
            "   WHERE p2.created_utc >= ? AND p2.created_utc < ?) AS n_chunks "
            "FROM posts WHERE created_utc >= ? AND created_utc < ?",
            (start.timestamp(), end.timestamp(), start.timestamp(), end.timestamp()),
        ).fetchone()
        if stats["n_posts"] > 0:
            windows.append(
                {
                    "week_start": start.date().isoformat(),
                    "week_end": end.date().isoformat(),
                    "n_posts": stats["n_posts"],
                    "n_chunks": stats["n_chunks"],
                }
            )
        end = start
    return windows


def posts_in_week(conn: sqlite3.Connection, week_start: str) -> list[sqlite3.Row]:
    """Posts whose created_utc falls in [week_start, week_start+7d)."""
    start = datetime.fromisoformat(week_start).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    return conn.execute(
        "SELECT * FROM posts WHERE created_utc >= ? AND created_utc < ? "
        "ORDER BY score DESC",
        (start.timestamp(), end.timestamp()),
    ).fetchall()

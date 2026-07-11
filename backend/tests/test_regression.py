"""Regression suite — each test pins a bug found (and fixed) during
development, or freezes behavior the rest of the system depends on.
"""
import time

from app import db
from app.rag.chunker import chunk_markdown


def test_week_windows_are_midnight_aligned(tmp_path):
    """Bug: week_windows anchored boundaries at the newest post's exact
    timestamp, while posts_in_week used midnight — the reported n_posts and
    the actual week query disagreed, silently dropping posts from views."""
    conn = db.connect(tmp_path / "w.sqlite")
    now = time.time()
    with conn:
        for i, age_days in enumerate([1, 3, 9, 16, 17]):
            conn.execute(
                "INSERT INTO posts(id, title, created_utc) VALUES (?,?,?)",
                (f"t3_{i}", f"p{i}", now - age_days * 86400),
            )
    for w in db.week_windows(conn):
        assert len(db.posts_in_week(conn, w["week_start"])) == w["n_posts"]
    conn.close()


GOLDEN_DOC = """# Golden post title
100 points · 5 comments · u/tester · 2026-01-01

Body paragraph for the golden snapshot.

## Top comments
- u/a (10 pts): first comment
- u/b (5 pts): second comment
"""

GOLDEN_IDS = ["032fc22673d5833d", "3adefd7165d2a2db"]


def test_chunk_id_golden_snapshot():
    """Chunk IDs key the committed vector store. Any chunker change that
    shifts them silently invalidates data/community.sqlite — this golden
    snapshot makes that loud. If you changed the chunker deliberately,
    re-ingest the committed database and update these IDs."""
    ids = [c.chunk_id for c in chunk_markdown("t3_golden", GOLDEN_DOC)]
    assert ids == GOLDEN_IDS

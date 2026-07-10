"""Unit tests: db helpers (windows, stats, meta, bm25 rebuild)."""
from app import db


def test_week_windows_match_posts_in_week(seeded):
    conn, _, _, _ = seeded
    windows = db.week_windows(conn)
    assert windows, "expected at least one window"
    total = 0
    for w in windows:
        posts = db.posts_in_week(conn, w["week_start"])
        assert len(posts) == w["n_posts"]
        total += len(posts)
    n_posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    assert total == n_posts  # windows partition all posts, none dropped


def test_windows_are_newest_first_and_seven_days(seeded):
    conn, _, _, _ = seeded
    windows = db.week_windows(conn)
    starts = [w["week_start"] for w in windows]
    assert starts == sorted(starts, reverse=True)
    for w in windows:
        assert (
            db.datetime.fromisoformat(w["week_end"])
            - db.datetime.fromisoformat(w["week_start"])
        ).days == 7


def test_bump_stats_upserts(seeded):
    conn, _, _, _ = seeded
    db.bump_stats(conn, ["c1", "c2"])
    db.bump_stats(conn, ["c1"])
    rows = {
        r["chunk_id"]: r["retrieved_count"]
        for r in conn.execute("SELECT * FROM retrieval_stats")
    }
    assert rows == {"c1": 2, "c2": 1}
    db.bump_stats(conn, [])  # no-op, no error


def test_meta_upsert(seeded):
    conn, _, _, _ = seeded
    db.set_meta(conn, "k", "v1")
    db.set_meta(conn, "k", "v2")
    assert db.get_meta(conn, "k") == "v2"
    assert db.get_meta(conn, "missing") is None


def test_build_bm25_covers_all_chunks(seeded):
    conn, _, _, _ = seeded
    idx = db.build_bm25(conn)
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert len(idx) == n_chunks


def test_empty_db_has_no_windows(tmp_path):
    conn = db.connect(tmp_path / "empty.sqlite")
    assert db.week_windows(conn) == []
    conn.close()

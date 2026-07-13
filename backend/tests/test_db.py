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


def test_daily_post_counts_zero_filled(seeded):
    conn, _, _, _ = seeded
    days = db.daily_post_counts(conn, days=14)
    assert len(days) == 14
    assert days == sorted(days, key=lambda d: d["date"])  # oldest first
    total_in_range = sum(d["n_posts"] for d in days)
    assert total_in_range > 0
    assert any(d["n_posts"] == 0 for d in days) or total_in_range == 16


def test_daily_post_counts_empty_db(tmp_path):
    conn = db.connect(tmp_path / "empty.sqlite")
    assert db.daily_post_counts(conn) == []
    conn.close()


def test_week_totals_match_windows(seeded):
    conn, _, _, weeks = seeded
    windows = {w["week_start"]: w for w in db.week_windows(conn)}
    for week_start in weeks:
        totals = db.week_totals(conn, week_start)
        assert totals["n_posts"] == windows[week_start]["n_posts"]
        assert totals["n_comments"] > 0


def test_reset_dataset_clears_everything(seeded):
    conn, _, _, _ = seeded
    db.set_meta(conn, "subreddit", "games@lemmy.world")
    db.set_meta(conn, "source", "lemmy")
    db.reset_dataset(conn)
    for table in ("posts", "chunks", "vec_chunks", "retrieval_stats"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert db.get_meta(conn, "subreddit") is None
    assert db.get_meta(conn, "source") is None
    assert db.week_windows(conn) == []

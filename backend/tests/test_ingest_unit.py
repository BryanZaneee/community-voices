"""Unit tests: ingest pipeline (markdown mapping, selection, idempotency)."""
import time

from app import db, ingest
from app.rag.embeddings import FakeEmbeddingProvider
from app.rag.vector_index import VectorIndex

from tests.conftest import DIM, make_posts


def test_post_to_markdown_structure_and_truncation():
    post = {
        "title": "Big news",
        "score": 123,
        "num_comments": 45,
        "author": "alice",
        "created_utc": 1780000000.0,
        "link_flair_text": "News",
        "selftext": "x" * (ingest.SELFTEXT_MAX_CHARS + 500),
    }
    comments = [
        {"author": "bob", "score": 9, "body": "y" * (ingest.COMMENT_MAX_CHARS + 200)}
    ]
    md = ingest.post_to_markdown(post, comments)
    lines = md.splitlines()
    assert lines[0] == "# Big news"
    assert "123 points" in lines[1] and "flair: News" in lines[1]
    assert "## Top comments" in md
    # truncation caps applied
    body_line = next(line for line in lines if line.startswith("- u/bob"))
    assert len(body_line) <= ingest.COMMENT_MAX_CHARS + 30
    assert "x" * (ingest.SELFTEXT_MAX_CHARS + 1) not in md


def test_select_for_comments_thresholds_and_caps():
    now = time.time()
    posts = []
    for i in range(ingest.TOP_POSTS_PER_WEEK + 10):
        posts.append(
            {
                "name": f"t3_{i}",
                "score": 1000 - i,
                "num_comments": 50,
                "created_utc": now - 3600,
            }
        )
    # low-discussion post is skipped even with a big score
    posts.append(
        {"name": "t3_quiet", "score": 9999, "num_comments": 1, "created_utc": now - 3600}
    )
    selected = ingest.select_for_comments(posts)
    names = {p["name"] for p in selected}
    assert "t3_quiet" not in names
    # cap applies to the score-ranked slate first, then the comment threshold
    # filters within it — so the quiet post consumes (and forfeits) one slot
    assert len(selected) == ingest.TOP_POSTS_PER_WEEK - 1
    assert len(selected) <= ingest.TOP_POSTS_PER_WEEK


def test_lemmy_post_mapping():
    post_view = {
        "post": {
            "id": 42,
            "name": "Steam Machine pricing announced",
            "published": "2026-07-01T12:30:00Z",
            "ap_id": "https://lemmy.world/post/42",
            "body": "Discussion body",
        },
        "creator": {"name": "someone"},
        "counts": {"score": 719, "comments": 537},
    }
    p = ingest._lemmy_post_to_common(post_view)
    assert p["name"] == "lemmy_42"
    assert p["title"] == "Steam Machine pricing announced"
    assert p["score"] == 719 and p["num_comments"] == 537
    assert p["selftext"] == "Discussion body"
    assert p["permalink"] == "https://lemmy.world/post/42"
    assert abs(p["created_utc"] - 1782909000.0) < 86400  # sane epoch, mid-2026


def test_ingest_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "i.sqlite")
    vec = VectorIndex(tmp_path / "i.sqlite", dim=DIM)
    provider = FakeEmbeddingProvider(dim=DIM)
    posts, comments = make_posts(n=8)

    first = ingest.ingest_posts(conn, "c", posts, comments, provider, vec)
    second = ingest.ingest_posts(conn, "c", posts, comments, provider, vec)
    assert first["chunks_new"] > 0
    assert second["chunks_new"] == 0
    assert second["chunks_total"] == first["chunks_total"]
    # posts upsert, not duplicate
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 8


def test_ingest_writes_meta_and_pca(tmp_path):
    conn = db.connect(tmp_path / "m.sqlite")
    vec = VectorIndex(tmp_path / "m.sqlite", dim=DIM)
    posts, comments = make_posts(n=6)
    ingest.ingest_posts(conn, "c/test", posts, comments, FakeEmbeddingProvider(dim=DIM), vec)
    assert db.get_meta(conn, "subreddit") == "c/test"
    assert db.get_meta(conn, "embedding_dim") == str(DIM)
    assert db.get_meta(conn, "pca") is not None
    assert db.get_meta(conn, "ingested_at") is not None


def test_run_ingest_persists_report_meta(tmp_path, monkeypatch):
    import json

    conn = db.connect(tmp_path / "r.sqlite")
    vec = VectorIndex(tmp_path / "r.sqlite", dim=DIM)
    posts, comments = make_posts(n=6)
    monkeypatch.setattr(
        ingest, "fetch_top_posts_lemmy", lambda s, c, w, p: posts
    )
    monkeypatch.setattr(
        ingest, "fetch_comments_lemmy", lambda s, p: comments[p["name"]]
    )
    report = ingest.run_ingest(
        conn, vec, FakeEmbeddingProvider(dim=DIM), "test", source="lemmy"
    )
    stored = json.loads(db.get_meta(conn, "ingest_report"))
    assert stored == report
    assert stored["posts"] == 6 and stored["comments"] > 0
    assert db.get_meta(conn, "source") == "lemmy"

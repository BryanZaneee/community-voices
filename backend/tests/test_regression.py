"""Regression suite — each test pins a bug found (and fixed) during
development, or freezes behavior the rest of the system depends on.
"""
import time

import pytest

from app import db, generate, ingest
from app.rag.bm25_index import BM25Index
from app.rag.chunker import chunk_markdown
from app.rag.embeddings import FakeEmbeddingProvider
from app.rag.retriever import Retriever
from app.rag.vector_index import VectorIndex

from tests.conftest import DIM, make_posts


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


def test_retrieval_mode_records_what_actually_ran(seeded, stub_llm):
    """Bug: a keyless retriever silently degraded hybrid->bm25 inside the
    search call, but the document row still recorded 'hybrid'."""
    conn, vec, _, weeks = seeded
    keyless_retriever = Retriever(
        embedding_provider=None, bm25_index=db.build_bm25(conn), vector_index=vec
    )
    doc_id = generate.generate_document(
        conn, keyless_retriever, week_start=weeks[0], mode="rag",
        model_key="deepseek-v4", retrieval_mode="hybrid",
    )
    row = conn.execute(
        "SELECT retrieval_mode FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row["retrieval_mode"] == "bm25"


def test_empty_retrieval_never_reaches_the_llm(seeded, stub_llm):
    """Bug: an empty retrieval produced a prompt with an empty <context>
    block and the model wrote a confused 'I have no context' document."""
    conn, _, retriever, _ = seeded
    with pytest.raises(ValueError):
        generate.generate_document(
            conn, retriever, week_start="1999-01-01", mode="rag",
            model_key="deepseek-v4",
        )
    assert stub_llm["complete"] == []  # the LLM was never called


def test_reingest_adds_zero_new_chunks(tmp_path):
    """Guards the content-hash chunk-ID scheme: if IDs ever stop being
    stable, overlapping ingests would silently duplicate the vector store
    (and double every retrieval stat)."""
    conn = db.connect(tmp_path / "r.sqlite")
    vec = VectorIndex(tmp_path / "r.sqlite", dim=DIM)
    provider = FakeEmbeddingProvider(dim=DIM)
    posts, comments = make_posts(n=6)
    ingest.ingest_posts(conn, "c", posts, comments, provider, vec)
    again = ingest.ingest_posts(conn, "c", posts, comments, provider, vec)
    assert again["chunks_new"] == 0
    conn.close()
    vec.close()


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


def test_bm25_zero_overlap_returns_empty_not_garbage():
    """Documents expected fallback behavior: when a facet query shares no
    tokens with the corpus, BM25 returns nothing (and RAG generation then
    refuses) rather than padding with irrelevant chunks."""
    idx = BM25Index()
    for c in chunk_markdown("t3_a", "# post\nlayoffs studio industry cuts"):
        idx.add(c)
    assert idx.search("astronomy telescopes nebula", k=5) == []

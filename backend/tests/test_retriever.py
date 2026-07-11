"""Unit tests: hybrid retriever and reciprocal rank fusion."""
import pytest

from app.rag.bm25_index import BM25Index
from app.rag.chunker import chunk_markdown
from app.rag.embeddings import FakeEmbeddingProvider
from app.rag.retriever import Retriever, reciprocal_rank_fusion
from app.rag.vector_index import VectorIndex

DIM = 32


def _chunk(post_id: str, text: str):
    return chunk_markdown(post_id, f"# {post_id}\n{text}")[0]


def test_rrf_exact_math():
    a, b, c = _chunk("pa", "aaa"), _chunk("pb", "bbb"), _chunk("pc", "ccc")
    fused = reciprocal_rank_fusion(
        bm25_results=[(a, 0.1), (b, 0.2)],
        vector_results=[(b, 0.3), (c, 0.4)],
        k=3,
        k_rrf=60,
    )
    scores = {r.chunk.path: r.score for r in fused}
    # b appears rank 2 (bm25) + rank 1 (vector); a and c appear once at rank 1/rank 2
    assert scores["pb"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["pa"] == pytest.approx(1 / 61)
    assert scores["pc"] == pytest.approx(1 / 62)
    assert fused[0].chunk.path == "pb"  # double-sourced chunk wins


def test_rrf_deterministic_tie_break():
    a, b = _chunk("p1", "x"), _chunk("p2", "y")
    fused = reciprocal_rank_fusion(
        bm25_results=[(a, 0.1)], vector_results=[(b, 0.1)], k=2
    )
    # equal scores -> ordered by (path, start_line) for stable output
    assert [r.chunk.path for r in fused] == ["p1", "p2"]


@pytest.fixture
def stack(tmp_path):
    provider = FakeEmbeddingProvider(dim=DIM)
    vec = VectorIndex(tmp_path / "v.sqlite", dim=DIM)
    bm25 = BM25Index()
    for pid, text in [
        ("p_layoffs", "studio layoffs job cuts"),
        ("p_roguelike", "roguelike deckbuilder cards"),
        ("p_prices", "subscription price increase"),
    ]:
        chunk = _chunk(pid, text)
        vec.add(chunk, provider.embed_documents([chunk.content])[0])
        bm25.add(chunk)
    yield provider, bm25, vec
    vec.close()


def test_hybrid_populates_both_legs(stack):
    provider, bm25, vec = stack
    r = Retriever(embedding_provider=provider, bm25_index=bm25, vector_index=vec)
    signals = r.search_with_signals("studio layoffs", k=2, mode="hybrid")
    assert signals.bm25_results and signals.vector_results
    assert signals.query_embedding is not None
    assert signals.fused[0].chunk.path == "p_layoffs"


def test_single_leg_modes(stack):
    provider, bm25, vec = stack
    r = Retriever(embedding_provider=provider, bm25_index=bm25, vector_index=vec)
    bm25_only = r.search_with_signals("layoffs", k=2, mode="bm25")
    assert bm25_only.vector_results == [] and bm25_only.query_embedding is None
    vec_only = r.search_with_signals("layoffs", k=2, mode="vector")
    assert vec_only.bm25_results == [] and vec_only.query_embedding is not None


def test_keyless_degrades_to_bm25(stack):
    _, bm25, vec = stack
    r = Retriever(embedding_provider=None, bm25_index=bm25, vector_index=vec)
    signals = r.search_with_signals("layoffs", k=2, mode="hybrid")
    assert signals.query_embedding is None
    assert signals.vector_results == []
    assert signals.fused  # bm25 leg still answers


def test_allowed_paths_filters_both_legs(stack):
    provider, bm25, vec = stack
    r = Retriever(embedding_provider=provider, bm25_index=bm25, vector_index=vec)
    signals = r.search_with_signals(
        "layoffs roguelike price", k=3, allowed_paths={"p_prices"}
    )
    assert {res.chunk.path for res in signals.fused} == {"p_prices"}
    assert all(c.path == "p_prices" for c, _ in signals.bm25_results)
    assert all(c.path == "p_prices" for c, _ in signals.vector_results)


def test_empty_query_raises(stack):
    provider, bm25, vec = stack
    r = Retriever(embedding_provider=provider, bm25_index=bm25, vector_index=vec)
    with pytest.raises(ValueError):
        r.search("   ")

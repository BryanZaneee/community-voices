"""Unit tests: BM25 index."""
import pytest

from app.rag.bm25_index import BM25Index
from app.rag.chunker import chunk_markdown


def _chunk(post_id: str, text: str):
    return chunk_markdown(post_id, f"# {post_id}\n{text}")[0]


@pytest.fixture
def index():
    idx = BM25Index()
    idx.add(_chunk("doc_layoffs", "studio layoffs cuts jobs " * 5))
    idx.add(_chunk("doc_roguelike", "roguelike deckbuilder cards " * 5))
    idx.add(_chunk("doc_mixed", "layoffs once, then mostly roguelike roguelike cards"))
    return idx


def test_relevance_ordering(index):
    results = index.search("studio layoffs", k=3)
    assert results[0][0].path == "doc_layoffs"


def test_scores_are_distances(index):
    # exp(-k * score): better match -> smaller value, results sorted ascending
    results = index.search("roguelike cards", k=3)
    values = [score for _, score in results]
    assert values == sorted(values)
    assert all(0 < v <= 1 for v in values)


def test_unknown_tokens_return_empty(index):
    assert index.search("zzz qqq nonexistent", k=5) == []


def test_k_respected_and_len(index):
    assert len(index.search("roguelike", k=1)) == 1
    assert len(index) == 3


def test_empty_index_and_bad_k(index):
    assert BM25Index().search("anything") == []
    with pytest.raises(ValueError):
        index.search("layoffs", k=0)

"""Unit tests: sqlite-vec vector index."""
import pytest

from app.rag.chunker import chunk_markdown
from app.rag.embeddings import FakeEmbeddingProvider
from app.rag.vector_index import VectorIndex

DIM = 32


def _chunk(post_id: str, text: str):
    return chunk_markdown(post_id, f"# {post_id}\n{text}")[0]


@pytest.fixture
def provider():
    return FakeEmbeddingProvider(dim=DIM)


@pytest.fixture
def index(tmp_path, provider):
    idx = VectorIndex(tmp_path / "vec.sqlite", dim=DIM)
    texts = {
        "p_layoffs": "studio layoffs job cuts industry",
        "p_roguelike": "roguelike deckbuilder cards synergy",
        "p_prices": "subscription price increase cost",
    }
    for pid, text in texts.items():
        chunk = _chunk(pid, text)
        idx.add(chunk, provider.embed_documents([chunk.content])[0])
    yield idx
    idx.close()


def test_nearest_neighbor_is_itself(index, provider):
    chunk = _chunk("p_layoffs", "studio layoffs job cuts industry")
    results = index.search(provider.embed_documents([chunk.content])[0], k=1)
    assert results[0][0].path == "p_layoffs"


def test_upsert_updates_in_place(index, provider):
    before = len(index)
    chunk = _chunk("p_layoffs", "studio layoffs job cuts industry")
    index.add(chunk, provider.embed_documents(["replacement text"])[0])
    assert len(index) == before  # same chunk_id -> update, not insert


def test_dim_mismatch_raises(index):
    chunk = _chunk("p_new", "text")
    with pytest.raises(ValueError):
        index.add(chunk, [0.0] * (DIM + 1))
    with pytest.raises(ValueError):
        index.search([0.0] * (DIM - 1), k=1)


def test_bad_k_raises(index, provider):
    with pytest.raises(ValueError):
        index.search(provider.embed_query("x"), k=0)


def test_all_embeddings_round_trip(index, provider):
    pairs = index.all_embeddings()
    assert len(pairs) == 3
    for chunk, emb in pairs:
        assert len(emb) == DIM
        # stored vector matches a fresh embedding of the same content
        fresh = provider.embed_documents([chunk.content])[0]
        assert emb == pytest.approx(fresh, abs=1e-6)

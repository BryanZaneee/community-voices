"""Unit tests: PCA projection."""
from app.rag.chunker import chunk_markdown
from app.rag.embeddings import FakeEmbeddingProvider
from app.rag.pca import compute_pca
from app.rag.vector_index import VectorIndex

DIM = 16


def _index_with(tmp_path, n: int) -> VectorIndex:
    provider = FakeEmbeddingProvider(dim=DIM)
    idx = VectorIndex(tmp_path / "p.sqlite", dim=DIM)
    for i in range(n):
        chunk = chunk_markdown(f"p{i}", f"# p{i}\nunique text number {i} " * 3)[0]
        idx.add(chunk, provider.embed_documents([chunk.content])[0])
    return idx


def test_too_few_chunks_returns_none(tmp_path):
    idx = _index_with(tmp_path, 2)
    assert compute_pca(idx, model="fake", dim=DIM) is None


def test_payload_shape_and_determinism(tmp_path):
    idx = _index_with(tmp_path, 6)
    a = compute_pca(idx, model="fake", dim=DIM)
    b = compute_pca(idx, model="fake", dim=DIM)
    assert a is not None
    assert len(a["points"]) == 6
    assert {"id", "path", "heading", "x", "y"} <= set(a["points"][0])
    assert a == b
    # points are not all collapsed to one spot
    xs = {p["x"] for p in a["points"]}
    assert len(xs) > 1

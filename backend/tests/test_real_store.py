"""Integration tests against the committed real data store.

Unlike the rest of the suite (synthetic corpus, fake embeddings), these run
on `data/community.sqlite`: real crawled Lemmy posts and real voyage-3-large
vectors. Still keyless: stored embeddings double as query vectors, so vector
search is exercised end-to-end without calling the embedding API. A final
test embeds a live query when VOYAGE_API_KEY is present (skipped in CI).
"""
from __future__ import annotations

import math
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app import db
from app.config import DB_PATH
from app.rag.vector_index import VectorIndex
from app.rag.retriever import Retriever

pytestmark = pytest.mark.skipif(
    not Path(DB_PATH).exists(), reason="committed data/community.sqlite not present"
)

DIM = 1024


@pytest.fixture(scope="module")
def conn():
    c = db.connect(DB_PATH)
    yield c
    c.close()


@pytest.fixture(scope="module")
def index():
    idx = VectorIndex(DB_PATH, dim=DIM)
    yield idx
    idx.close()


@pytest.fixture(scope="module")
def store(index):
    """All (chunk, embedding) pairs from the committed store."""
    return index.all_embeddings()


def test_corpus_shape(conn, store):
    posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    vecs = conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    assert posts > 100
    assert chunks > 300
    assert chunks == vecs == len(store)
    assert db.get_meta(conn, "embedding_model") == "voyage-3-large"
    assert int(db.get_meta(conn, "embedding_dim")) == DIM


def test_embeddings_are_real_vectors(store):
    sample = random.Random(7).sample(store, 25)
    norms = []
    for _, vec in sample:
        assert len(vec) == DIM
        norm = math.sqrt(sum(v * v for v in vec))
        assert norm > 0.1, "zero/near-zero embedding in committed store"
        norms.append(round(norm, 3))
    # a fake or corrupt store would collapse to identical vectors
    assert len({tuple(vec[:8]) for _, vec in sample}) == len(sample)


def test_knn_self_retrieval(index, store):
    for chunk, vec in random.Random(11).sample(store, 10):
        results = index.search(vec, k=5)
        top_chunk, top_dist = results[0]
        assert top_chunk.chunk_id == chunk.chunk_id
        assert top_dist == pytest.approx(0.0, abs=1e-3)
        dists = [d for _, d in results]
        assert dists == sorted(dists)


def test_bm25_on_real_corpus(conn):
    bm25 = db.build_bm25(conn)
    assert len(bm25) > 300
    results = bm25.search("game release players", k=10)
    assert results, "BM25 over the real corpus returned nothing"
    # scores are distance-transformed: lower is better, ascending order
    scores = [s for _, s in results]
    assert scores == sorted(scores)
    assert all("game" in c.content.lower() or "player" in c.content.lower()
               or "release" in c.content.lower() for c, _ in results[:3])


class _StoredVectorProvider:
    """Returns a fixed stored embedding: real-vector search without an API."""

    def __init__(self, vec: list[float]):
        self.vec = vec
        self.model = "stored"

    def embed_query(self, text: str) -> list[float]:
        return self.vec

    def embed_documents(self, texts):
        return [self.vec for _ in texts]


def test_retriever_vector_mode_on_real_store(conn, index, store):
    chunk, vec = store[42]
    retriever = Retriever(
        embedding_provider=_StoredVectorProvider(vec),
        bm25_index=db.build_bm25(conn),
        vector_index=index,
    )
    results = retriever.search("placeholder query", k=5, mode="vector")
    assert results[0].chunk.chunk_id == chunk.chunk_id


def test_retriever_week_filter_on_real_store(conn, index, store):
    chunk, vec = store[0]
    other_paths = {c.path for c, _ in store if c.path != chunk.path}
    allowed = set(random.Random(3).sample(sorted(other_paths), 20))
    retriever = Retriever(
        embedding_provider=_StoredVectorProvider(vec),
        bm25_index=db.build_bm25(conn),
        vector_index=index,
    )
    results = retriever.search("placeholder query", k=8, mode="vector",
                               allowed_paths=allowed)
    assert results, "week filter returned nothing from the real store"
    assert all(r.chunk.path in allowed for r in results)


@pytest.mark.skipif(not os.environ.get("VOYAGE_API_KEY"),
                    reason="live Voyage test needs VOYAGE_API_KEY")
def test_live_voyage_query_against_real_store(index):
    from app.rag.embeddings import VoyageEmbeddingProvider

    provider = VoyageEmbeddingProvider(model="voyage-3-large", dim=DIM)
    vec = provider.embed_query("what video game did the community discuss")
    assert len(vec) == DIM
    results = index.search(vec, k=5)
    assert len(results) == 5
    assert results[0][1] < results[-1][1] or len({d for _, d in results}) == 1

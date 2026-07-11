"""Round-trip check of the ported RAG stack: chunk -> embed(fake) -> index ->
retrieve, plus printed perf timings at ~1k chunks (no API keys needed).

Run from backend/: python -m pytest tests -s
"""
from __future__ import annotations

import time

from app.rag.bm25_index import BM25Index
from app.rag.chunker import chunk_markdown
from app.rag.embeddings import FakeEmbeddingProvider
from app.rag.retriever import Retriever
from app.rag.vector_index import VectorIndex

DIM = 64


def _doc(post_id: str, title: str, body: str, comments: list[str]) -> str:
    lines = [f"# {title}", "", body, "", "## Top comments"]
    lines += [f"- u/tester: {c}" for c in comments]
    return "\n".join(lines)


def _build(n_posts: int):
    provider = FakeEmbeddingProvider(dim=DIM)
    vec = VectorIndex(":memory:", dim=DIM)
    bm25 = BM25Index()
    all_chunks = []
    topics = [
        ("studio layoffs hit publishers", "thousands of developers lost jobs this week"),
        ("new roguelike deckbuilder released", "the community loves the card synergies"),
        ("subscription price increase announced", "players are furious about the cost"),
        ("speedrun world record broken", "an incredible glitchless run"),
        ("remaster of a classic rpg", "nostalgia and improved graphics"),
    ]
    for i in range(n_posts):
        title, body = topics[i % len(topics)]
        md = _doc(
            f"t3_{i:05d}",
            f"{title} #{i}",
            "\n".join([body] * 80),  # multi-line, long enough to split into chunks
            [f"comment about {title} number {j}" for j in range(8)],
        )
        chunks = chunk_markdown(f"t3_{i:05d}", md)
        all_chunks.extend(chunks)
        vectors = provider.embed_documents([c.content for c in chunks])
        vec.add_documents(zip(chunks, vectors))
        for c in chunks:
            bm25.add(c)
    return provider, vec, bm25, all_chunks


def test_roundtrip_and_perf():
    t0 = time.perf_counter()
    provider, vec, bm25, chunks = _build(n_posts=200)
    build_ms = (time.perf_counter() - t0) * 1000
    assert len(chunks) >= 600, f"expected corpus-scale chunk count, got {len(chunks)}"
    assert len(vec) == len(chunks)

    retriever = Retriever(
        embedding_provider=provider, bm25_index=bm25, vector_index=vec
    )

    # Hybrid search finds the topically-right chunks.
    t0 = time.perf_counter()
    signals = retriever.search_with_signals("studio layoffs developers jobs", k=8)
    search_ms = (time.perf_counter() - t0) * 1000
    assert signals.fused, "hybrid search returned nothing"
    assert any(
        r.chunk.heading_path[0].startswith("studio layoffs") for r in signals.fused
    )

    # Week-style path filter only returns allowed posts.
    allowed = {f"t3_{i:05d}" for i in range(0, 50)}
    scoped = retriever.search("price increase", k=8, allowed_paths=allowed)
    assert scoped and all(r.chunk.path in allowed for r in scoped)

    # BM25-only mode works with no embedding provider at all.
    keyless = Retriever(embedding_provider=None, bm25_index=bm25, vector_index=vec)
    fallback = keyless.search("deckbuilder card synergies", k=5)
    assert fallback

    # Stable chunk IDs: re-chunking identical content yields identical IDs.
    md = _doc("t3_00000", "stable check", "same content", ["same comment"])
    ids_a = [c.chunk_id for c in chunk_markdown("t3_00000", md)]
    ids_b = [c.chunk_id for c in chunk_markdown("t3_00000", md)]
    assert ids_a == ids_b

    print(
        f"\n[perf] {len(chunks)} chunks | build+embed(fake)+index: {build_ms:.0f}ms"
        f" | hybrid search: {search_ms:.1f}ms"
        f" (bm25 {signals.timings['bm25_ms']}ms, vector {signals.timings['vector_ms']}ms)"
    )

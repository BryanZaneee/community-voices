"""Hybrid BM25 + vector retrieval with plain Reciprocal Rank Fusion.

Adapted from easyagent: profile plumbing removed; adds an optional embedding
leg (BM25-only when no Voyage key), a retrieval_mode switch used by the
retrieval-vs-retrieval comparison, and an allowed_paths filter so searches
can be scoped to one week's posts.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from app.rag.chunker import Chunk
from app.rag.embeddings import EmbeddingProvider

DEFAULT_RRF_K = 60

RetrievalMode = Literal["hybrid", "vector", "bm25"]


@dataclass(frozen=True)
class RetrievalResult:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class RetrievalSignals:
    query_embedding: list[float] | None
    bm25_results: list[tuple[Chunk, float]]
    vector_results: list[tuple[Chunk, float]]
    fused: list[RetrievalResult]
    timings: dict[str, float]


class Retriever:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None,
        bm25_index,
        vector_index,
    ) -> None:
        self.embedding = embedding_provider
        self.bm25 = bm25_index
        self.vector = vector_index

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        mode: RetrievalMode = "hybrid",
        allowed_paths: set[str] | None = None,
        k_rrf: int = DEFAULT_RRF_K,
    ) -> list[RetrievalResult]:
        return self.search_with_signals(
            query, k=k, mode=mode, allowed_paths=allowed_paths, k_rrf=k_rrf
        ).fused

    def search_with_signals(
        self,
        query: str,
        *,
        k: int = 5,
        mode: RetrievalMode = "hybrid",
        allowed_paths: set[str] | None = None,
        k_rrf: int = DEFAULT_RRF_K,
    ) -> RetrievalSignals:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if mode in ("hybrid", "vector") and self.embedding is None:
            mode = "bm25"  # graceful degradation without an embedding key
        k = max(1, int(k))
        # Over-fetch: filtering by week happens after the index search, so
        # pull a deep candidate pool when a filter is active.
        candidate_k = k * (12 if allowed_paths is not None else 4)

        bm25_results: list[tuple[Chunk, float]] = []
        bm25_ms = 0.0
        if mode in ("hybrid", "bm25"):
            t0 = time.perf_counter()
            bm25_results = self.bm25.search(query, k=candidate_k)
            bm25_ms = round((time.perf_counter() - t0) * 1000, 1)

        query_embedding: list[float] | None = None
        vector_results: list[tuple[Chunk, float]] = []
        embed_ms = vector_ms = 0.0
        if mode in ("hybrid", "vector"):
            t0 = time.perf_counter()
            query_embedding = self.embedding.embed_query(query)
            embed_ms = round((time.perf_counter() - t0) * 1000, 1)
            t0 = time.perf_counter()
            vector_results = self.vector.search(query_embedding, k=candidate_k)
            vector_ms = round((time.perf_counter() - t0) * 1000, 1)

        if allowed_paths is not None:
            bm25_results = [r for r in bm25_results if r[0].path in allowed_paths]
            vector_results = [r for r in vector_results if r[0].path in allowed_paths]

        fused = reciprocal_rank_fusion(
            bm25_results=bm25_results,
            vector_results=vector_results,
            k=k,
            k_rrf=k_rrf,
        )
        return RetrievalSignals(
            query_embedding=query_embedding,
            bm25_results=bm25_results,
            vector_results=vector_results,
            fused=fused,
            timings={
                "embed_ms": embed_ms,
                "bm25_ms": bm25_ms,
                "vector_ms": vector_ms,
            },
        )


def reciprocal_rank_fusion(
    *,
    bm25_results: list[tuple[Chunk, float]],
    vector_results: list[tuple[Chunk, float]],
    k: int = 5,
    k_rrf: int = DEFAULT_RRF_K,
) -> list[RetrievalResult]:
    """Fuse ranked sparse and dense results using Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    for results in (bm25_results, vector_results):
        for rank, (chunk, _raw) in enumerate(results, start=1):
            chunks[chunk.chunk_id] = chunk
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (
                k_rrf + rank
            )
    ranked = sorted(
        scores,
        key=lambda cid: (-scores[cid], chunks[cid].path, chunks[cid].start_line),
    )
    return [
        RetrievalResult(chunk=chunks[cid], score=scores[cid])
        for cid in ranked[: max(1, int(k))]
    ]

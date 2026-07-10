"""BM25 sparse retrieval index (in-memory, rebuilt from the chunks table).

The exp(-k*raw_score) post-transform turns BM25 scores into a
monotonically-decreasing "distance" so smaller values are better, which lets
the hybrid Retriever fuse BM25 with vector cosine-distance scores without
sign juggling.

Perf note vs. the original: per-document token Counters are computed once at
add() time instead of on every query, so scoring is dict lookups only.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Callable

from app.rag.chunker import Chunk


class BM25Index:
    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Callable[[str], list[str]] | None = None,
    ):
        self.chunks: list[Chunk] = []
        self._doc_counts: list[Counter[str]] = []
        self._doc_len: list[int] = []
        self._doc_freqs: dict[str, int] = {}
        self._avg_doc_len: float = 0.0
        self._idf: dict[str, float] = {}
        self._index_built: bool = False
        self.k1 = k1
        self.b = b
        self._tokenizer = tokenizer if tokenizer else self._default_tokenizer

    @staticmethod
    def _default_tokenizer(text: str) -> list[str]:
        tokens = re.split(r"\W+", text.lower())
        return [t for t in tokens if t]

    def add(self, chunk: Chunk) -> None:
        if not isinstance(chunk, Chunk):
            raise TypeError("chunk must be a Chunk.")
        tokens = self._tokenizer(chunk.content)
        self.chunks.append(chunk)
        counts = Counter(tokens)
        self._doc_counts.append(counts)
        self._doc_len.append(len(tokens))
        for tok in counts:
            self._doc_freqs[tok] = self._doc_freqs.get(tok, 0) + 1
        self._index_built = False

    def _build_index(self) -> None:
        if not self.chunks:
            self._avg_doc_len = 0.0
            self._idf = {}
            self._index_built = True
            return
        self._avg_doc_len = sum(self._doc_len) / len(self.chunks)
        n = len(self.chunks)
        self._idf = {
            term: math.log(((n - freq + 0.5) / (freq + 0.5)) + 1)
            for term, freq in self._doc_freqs.items()
        }
        self._index_built = True

    def _score(self, query_tokens: list[str], doc_index: int) -> float:
        score = 0.0
        counts = self._doc_counts[doc_index]
        doc_len = self._doc_len[doc_index]
        for tok in query_tokens:
            idf = self._idf.get(tok)
            if idf is None:
                continue
            tf = counts.get(tok, 0)
            num = idf * tf * (self.k1 + 1)
            den = tf + self.k1 * (
                1 - self.b + self.b * (doc_len / self._avg_doc_len)
            )
            score += num / (den + 1e-9)
        return score

    def search(
        self,
        query_text: str,
        k: int = 5,
        score_normalization_factor: float = 0.1,
    ) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        if k <= 0:
            raise ValueError("k must be a positive integer.")
        if not self._index_built:
            self._build_index()
        if self._avg_doc_len == 0:
            return []
        query_tokens = self._tokenizer(query_text)
        if not query_tokens:
            return []
        raw: list[tuple[float, Chunk]] = []
        for i in range(len(self.chunks)):
            s = self._score(query_tokens, i)
            if s > 1e-9:
                raw.append((s, self.chunks[i]))
        raw.sort(key=lambda item: item[0], reverse=True)
        out: list[tuple[Chunk, float]] = []
        for raw_score, chunk in raw[:k]:
            normalized = math.exp(-score_normalization_factor * raw_score)
            out.append((chunk, normalized))
        out.sort(key=lambda item: item[1])
        return out

    def __len__(self) -> int:
        return len(self.chunks)

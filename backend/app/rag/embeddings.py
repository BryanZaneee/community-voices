"""Embedding providers: Voyage AI (real) and a deterministic fake for tests."""
from __future__ import annotations

import hashlib
import math
import os
import re
import time
from typing import Protocol


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding backend is missing or misconfigured."""


class EmbeddingProvider(Protocol):
    backend: str
    model: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class FakeEmbeddingProvider:
    """Deterministic token-hash embeddings for tests and keyless smoke runs."""

    backend = "fake"

    def __init__(self, *, dim: int = 64, model: str | None = None) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim
        self.model = model or f"fake-{dim}d"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(str(text).lower())
        if not tokens:
            tokens = [str(text)]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        return _normalize(vec)


_VOYAGE_DIMS = {
    "voyage-3-large": 1024,
    "voyage-3": 1024,
    "voyage-3-lite": 512,
}


class VoyageEmbeddingProvider:
    backend = "voyage"

    def __init__(
        self,
        *,
        model: str = "voyage-3-large",
        api_key: str | None = None,
        dim: int | None = None,
    ) -> None:
        self.model = model
        self.dim = dim or _VOYAGE_DIMS.get(model, 1024)
        self._api_key = api_key if api_key is not None else os.environ.get("VOYAGE_API_KEY")
        if not self._api_key:
            raise EmbeddingProviderError(
                "VOYAGE_API_KEY is required for Voyage embeddings"
            )
        try:
            import voyageai
        except ModuleNotFoundError as exc:
            raise EmbeddingProviderError(
                "Voyage embeddings require the voyageai package "
                "(pip install -r backend/requirements.txt)."
            ) from exc
        self._client = voyageai.Client(api_key=self._api_key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, input_type="document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], input_type="query")[0]

    def _embed(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        # Retry with exponential backoff on rate-limit errors. The Voyage free
        # tier allows only 3 requests/min and 10K tokens/min, so a full ingest
        # can outrun the window and must wait it out.
        from voyageai.error import RateLimitError

        delay = 20.0
        for attempt in range(6):
            try:
                response = self._client.embed(
                    texts, model=self.model, input_type=input_type
                )
                return [
                    [float(value) for value in embedding]
                    for embedding in response.embeddings
                ]
            except RateLimitError:
                if attempt >= 5:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 120.0)
        raise RuntimeError("unreachable")  # pragma: no cover


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vec))
    if norm <= 0:
        return vec
    return [value / norm for value in vec]

"""Unit tests: embedding providers."""
import math

import pytest

from app.rag.embeddings import (
    EmbeddingProviderError,
    FakeEmbeddingProvider,
    VoyageEmbeddingProvider,
)


def test_fake_is_deterministic_and_normalized():
    p = FakeEmbeddingProvider(dim=48)
    a = p.embed_query("hello gaming world")
    b = p.embed_query("hello gaming world")
    assert a == b
    assert len(a) == 48
    assert math.sqrt(sum(v * v for v in a)) == pytest.approx(1.0)


def test_fake_documents_match_query_embedding():
    p = FakeEmbeddingProvider(dim=16)
    assert p.embed_documents(["same text"])[0] == p.embed_query("same text")


def test_fake_different_text_differs():
    p = FakeEmbeddingProvider(dim=64)
    assert p.embed_query("layoffs") != p.embed_query("roguelike")


def test_fake_rejects_bad_dim():
    with pytest.raises(ValueError):
        FakeEmbeddingProvider(dim=0)


def test_voyage_requires_key(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(EmbeddingProviderError):
        VoyageEmbeddingProvider()

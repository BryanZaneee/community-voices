"""Shared fixtures: synthetic corpus, seeded DB, stubbed LLM, API client.

Every fixture is offline — embeddings come from FakeEmbeddingProvider and all
LLM entry points are monkeypatched. Tests must pass with no API keys at all.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app import db, ingest, llm
from app.rag.embeddings import FakeEmbeddingProvider
from app.rag.retriever import Retriever
from app.rag.vector_index import VectorIndex

DIM = 64

# Facet-friendly vocabulary so BM25 matches the canonical retrieval queries.
TOPICS = [
    (
        "Massive studio layoffs announced",
        "The community is asking questions about the layoffs this week and "
        "people debate what happens next in heated discussions.",
    ),
    (
        "Indie roguelike recommendations thread",
        "Recommendations and tips for the most popular indie roguelike posts "
        "this week, with guides for new players.",
    ),
    (
        "Subscription price increase controversy",
        "Controversy and disagreement over the subscription price increase "
        "announcement dominated the front page.",
    ),
    (
        "Upcoming releases megathread",
        "Upcoming releases and events discussion; the community mood is "
        "hopeful with plenty of jokes and running themes.",
    ),
]


def make_posts(n: int = 16, weeks: int = 3, now: float | None = None) -> tuple[list[dict], dict]:
    """Reddit/Lemmy-shaped post dicts spread over `weeks` trailing windows."""
    now = now or time.time()
    posts = []
    for i in range(n):
        title, body = TOPICS[i % len(TOPICS)]
        age_days = (i % (weeks * 3)) * 2.4  # spread across the window span
        posts.append(
            {
                "name": f"t3_syn{i:03d}",
                "title": f"{title} #{i}",
                "author": f"user{i}",
                "score": 4000 - i * 90,
                "num_comments": 120,
                "created_utc": now - age_days * 86400,
                "permalink": f"/r/test/comments/syn{i:03d}/",
                "link_flair_text": "Discussion" if i % 2 else None,
                "selftext": (body + "\n") * 5,
            }
        )
    comments = {
        p["name"]: [
            {"author": "c1", "score": 40, "body": f"Strong opinion about {p['title']}"},
            {"author": "c2", "score": 12, "body": "Counterpoint with detail " * 10},
        ]
        for p in posts
    }
    return posts, comments


@pytest.fixture
def seeded(tmp_path):
    """(conn, vector_index, retriever, weeks) over a real tmp sqlite file."""
    db_path = tmp_path / "test.sqlite"
    conn = db.connect(db_path)
    vec = VectorIndex(db_path, dim=DIM)
    provider = FakeEmbeddingProvider(dim=DIM)
    posts, comments = make_posts()
    ingest.ingest_posts(conn, "test-community", posts, comments, provider, vec)
    retriever = Retriever(
        embedding_provider=provider,
        bm25_index=db.build_bm25(conn),
        vector_index=vec,
    )
    weeks = [w["week_start"] for w in db.week_windows(conn)]
    yield conn, vec, retriever, weeks
    conn.close()
    vec.close()


STUB_DOC = """# Community Voices — test-community — Week of {week}

## What the community talked about
Layoffs and roguelikes dominated, per *{title}*.

## Standout threads
- A big thread happened.

## Predictions for next week
- Prediction alpha for {week}: more layoffs talk.
- Prediction beta: roguelike sequels.
"""


def stub_report(week: str, title: str) -> dict:
    """A REPORT_SCHEMA-shaped payload the stubbed LLM returns."""
    return {
        "headline": "Layoffs and roguelikes dominated the week",
        "lede": f"Layoffs and roguelikes dominated, per *{title}*.",
        "topics": [
            {"name": "Studio layoffs", "summary": f"Layoffs talk, per *{title}*.",
             "detail": "A deeper dive into the layoffs discussion.",
             "share_pct": 40, "threads": 12},
            {"name": "Roguelike recommendations", "summary": "Roguelikes trended.",
             "detail": "More roguelike specifics.", "share_pct": 30, "threads": None},
            {"name": "Subscription pricing", "summary": "Price debate continued.",
             "detail": "More pricing specifics.", "share_pct": 20, "threads": 6},
        ],
        "standouts": ["A big thread happened."],
        "predictions": [
            {"title": f"Prediction alpha for {week}: more layoffs talk",
             "confidence": 72, "rationale": "Momentum from this week.",
             "signals": ["thread volume rising"]},
            {"title": "Prediction beta: roguelike sequels", "confidence": 55,
             "rationale": "Recommendation threads keep growing.",
             "signals": ["repeat threads"]},
            {"title": "Prediction gamma: pricing poll", "confidence": 40,
             "rationale": "Admins teased a poll.", "signals": ["mod comment"]},
        ],
    }


@pytest.fixture
def stub_llm(monkeypatch):
    """Stub llm.complete + llm.judge_json; records every call's prompts."""
    import json as _json

    calls = {"complete": [], "judge": []}

    def fake_complete(model_key, system, user, json_schema=None):
        from app import config

        if model_key not in config.MODELS:  # mirror _require_key's registry check
            raise llm.ModelUnavailable(f"unknown model: {model_key}")
        calls["complete"].append({"model_key": model_key, "system": system, "user": user})
        week = system.split("week of ")[-1].split(" ")[0] if "week of" in system else "?"
        title = "Massive studio layoffs announced #0"
        text = (
            _json.dumps(stub_report(week, title))
            if json_schema is not None
            else STUB_DOC.format(week=week, title=title)
        )
        return llm.GenResult(
            text=text,
            model_key=model_key,
            input_tokens=1000,
            output_tokens=500,
            latency_ms=42,
        )

    def fake_judge(doc_a, doc_b):
        calls["judge"].append({"a": doc_a, "b": doc_b})
        crit = {"specificity": 3, "evidence": 3, "temporal_grounding": 3, "usefulness": 3}
        return {"scores": {"a": crit, "b": dict(crit, specificity=5)},
                "winner": "b", "rationale": "stubbed"}

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(llm, "judge_json", fake_judge)
    return calls


@pytest.fixture
def keyless(monkeypatch):
    """Remove every provider key so degradation paths are exercised."""
    for var in ("VOYAGE_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
                "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def client(tmp_path, monkeypatch, keyless, stub_llm):
    """FastAPI TestClient over a freshly seeded tmp DB, fully offline."""
    from fastapi.testclient import TestClient

    from app import config
    from app import main as app_main

    db_path = tmp_path / "api.sqlite"
    conn = db.connect(db_path)
    vec = VectorIndex(db_path, dim=DIM)
    posts, comments = make_posts()
    ingest.ingest_posts(
        conn, "test-community", posts, comments, FakeEmbeddingProvider(dim=DIM), vec
    )
    conn.close()
    vec.close()

    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "EMBEDDING_DIM", DIM)
    with TestClient(app_main.app) as test_client:
        yield test_client

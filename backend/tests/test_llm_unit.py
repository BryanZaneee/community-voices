"""Unit tests: llm layer (registry, cost math, judge fallback)."""
import pytest

from app import llm


def test_est_cost_usd():
    r = llm.GenResult(
        text="x", model_key="claude-haiku-4-5",
        input_tokens=1_000_000, output_tokens=1_000_000, latency_ms=1,
    )
    # haiku: $1 in + $5 out per MTok
    assert r.est_cost_usd == pytest.approx(6.0)


def test_require_key_unknown_model():
    with pytest.raises(llm.ModelUnavailable):
        llm._require_key("not-a-model")


def test_require_key_missing_env(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(llm.ModelUnavailable):
        llm._require_key("deepseek-v4")


def test_complete_unknown_model_raises():
    with pytest.raises(llm.ModelUnavailable):
        llm.complete("nope", "sys", "user")


def test_judge_falls_back_to_deepseek(monkeypatch):
    def boom(_):
        raise RuntimeError("anthropic down / no credits")

    canned = (
        '{"scores": {"a": {"specificity": 2, "evidence": 2, '
        '"temporal_grounding": 2, "usefulness": 2}, '
        '"b": {"specificity": 5, "evidence": 5, '
        '"temporal_grounding": 5, "usefulness": 5}}, '
        '"winner": "b", "rationale": "fallback ran"}'
    )
    calls = []

    def fake_deepseek(content):
        calls.append(content)
        return canned

    monkeypatch.setattr(llm, "_judge_anthropic", boom)
    monkeypatch.setattr(llm, "_judge_deepseek", fake_deepseek)
    out = llm.judge_json("doc a", "doc b")
    assert out["winner"] == "b" and out["rationale"] == "fallback ran"
    assert "doc a" in calls[0] and "doc b" in calls[0]


def test_judge_prefers_anthropic_when_it_works(monkeypatch):
    monkeypatch.setattr(llm, "_judge_anthropic", lambda _: '{"scores": null, "winner": "a", "rationale": "anthropic"}')
    monkeypatch.setattr(
        llm, "_judge_deepseek",
        lambda _: (_ for _ in ()).throw(AssertionError("fallback must not run")),
    )
    assert llm.judge_json("a", "b")["rationale"] == "anthropic"


def test_judge_unparseable_output_degrades(monkeypatch):
    monkeypatch.setattr(llm, "_judge_anthropic", lambda _: "not json at all")
    out = llm.judge_json("a", "b")
    assert out["winner"] == "tie"
    assert out["scores"] is None
    assert "not json" in out["rationale"]

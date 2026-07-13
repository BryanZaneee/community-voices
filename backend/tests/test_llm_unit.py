"""Unit tests: llm layer (registry, cost math, judge parse degradation)."""
import pytest

from app import llm


def test_est_cost_usd():
    r = llm.GenResult(
        text="x", model_key="deepseek-v4",
        input_tokens=1_000_000, output_tokens=1_000_000, latency_ms=1,
    )
    # deepseek-v4: $0.14 in + $0.28 out per MTok (V4-Flash cache-miss rates)
    assert r.est_cost_usd == pytest.approx(0.42)


def test_est_cost_unknown_model_is_none():
    assert llm.est_cost_usd("retired-model", 1000, 1000) is None


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


def test_model_registry_prices_match_vendor_list():
    """Spot-check registry prices against vendor list rates (2026-07-13)."""
    from app import config

    assert config.MODELS["deepseek-v4-flash"]["price_in"] == 0.14
    assert config.MODELS["deepseek-v4-flash"]["price_out"] == 0.28
    assert config.MODELS["claude-opus-4-8"]["price_in"] == 5.00
    assert config.MODELS["claude-opus-4-8"]["price_out"] == 25.00
    assert config.MODELS["claude-sonnet-5"]["price_in"] == 2.00
    assert config.MODELS["claude-sonnet-5"]["price_out"] == 10.00


def test_anthropic_json_schema_strips_unsupported_constraints():
    from app.generate import REPORT_SCHEMA

    schema = llm._anthropic_json_schema(REPORT_SCHEMA)
    topics = schema["properties"]["topics"]
    assert "maxItems" not in topics
    assert topics.get("minItems") in (None, 0, 1)
    share = topics["items"]["properties"]["share_pct"]
    assert share.get("type") != ["integer", "null"]
    assert "anyOf" in share


def test_judge_unparseable_output_degrades(monkeypatch):
    class FakeChoice:
        message = type("M", (), {"content": "not json at all"})()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        @staticmethod
        def create(**_):
            return FakeResp()

    class FakeClient:
        chat = type("C", (), {"completions": FakeCompletions()})()

    import openai

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", lambda **_: FakeClient())
    out = llm.judge_json("a", "b")
    assert out["winner"] == "tie"
    assert out["scores"] is None
    assert "not json" in out["rationale"]

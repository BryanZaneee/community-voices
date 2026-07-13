"""Thin LLM client layer over the model registry in config.MODELS.

complete()  -> generation via the OpenAI-compatible DeepSeek API
judge_json() -> blind comparison scoring via DeepSeek JSON mode
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from app import config

MAX_TOKENS = 4096


class ModelUnavailable(RuntimeError):
    """The requested model's API key is not configured."""


def est_cost_usd(
    model_key: str, input_tokens: float, output_tokens: float
) -> float | None:
    """USD cost from token counts and the registry's per-MTok prices."""
    cfg = config.MODELS.get(model_key)
    if cfg is None:
        return None
    return (
        input_tokens * cfg["price_in"] + output_tokens * cfg["price_out"]
    ) / 1_000_000


@dataclass(frozen=True)
class GenResult:
    text: str
    model_key: str
    input_tokens: int
    output_tokens: int
    latency_ms: int

    @property
    def est_cost_usd(self) -> float:
        return est_cost_usd(self.model_key, self.input_tokens, self.output_tokens)


def _require_key(model_key: str) -> dict:
    cfg = config.MODELS.get(model_key)
    if cfg is None:
        raise ModelUnavailable(f"unknown model: {model_key}")
    if not os.environ.get(cfg["key_env"]):
        raise ModelUnavailable(
            f"{cfg['label']} requires the {cfg['key_env']} environment variable"
        )
    return cfg


def complete(
    model_key: str, system: str, user: str, json_schema: dict | None = None
) -> GenResult:
    """One completion via the OpenAI-compatible DeepSeek API. With
    json_schema, JSON mode is enabled and the schema appended to system."""
    cfg = _require_key(model_key)
    t0 = time.perf_counter()
    from openai import OpenAI

    kwargs = {}
    if json_schema is not None:
        kwargs["response_format"] = {"type": "json_object"}
        system = (
            system
            + "\nRespond ONLY with JSON matching this schema:\n"
            + json.dumps(json_schema)
        )
    client = OpenAI(api_key=os.environ[cfg["key_env"]], base_url=cfg["base_url"])
    resp = client.chat.completions.create(
        model=cfg["model"],
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **kwargs,
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    return GenResult(
        text=text,
        model_key=model_key,
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                "a": {"$ref": "#/$defs/criteria"},
                "b": {"$ref": "#/$defs/criteria"},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        "winner": {"type": "string", "enum": ["a", "b", "tie"]},
        "rationale": {"type": "string"},
    },
    "required": ["scores", "winner", "rationale"],
    "additionalProperties": False,
    "$defs": {
        "criteria": {
            "type": "object",
            "properties": {
                "specificity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                "evidence": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                "temporal_grounding": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                "usefulness": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            },
            "required": ["specificity", "evidence", "temporal_grounding", "usefulness"],
            "additionalProperties": False,
        }
    },
}

JUDGE_SYSTEM = """You judge two "Community Voices" documents (A and B) that each
summarize what an online community discussed in a given week and predict the next week.
Score each document 1-5 on:
- specificity: concrete posts, names, numbers vs. vague generalities
- evidence: claims grounded in real cited discussions vs. unsupported
- temporal_grounding: reflects that specific week vs. timeless filler
- usefulness: how informative for someone catching up on the community
Pick the overall winner ("a", "b", or "tie") and give a 2-3 sentence rationale.
Judge only the content; ignore formatting differences."""


def judge_json(doc_a_md: str, doc_b_md: str) -> dict:
    """Compare two documents blind via DeepSeek JSON mode. Never raises on
    parse issues — raw text lands in the rationale."""
    cfg = _require_key(config.DEFAULT_MODEL_KEY)
    from openai import OpenAI

    client = OpenAI(api_key=os.environ[cfg["key_env"]], base_url=cfg["base_url"])
    resp = client.chat.completions.create(
        model=cfg["model"],
        max_tokens=1024,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": JUDGE_SYSTEM
                + "\nRespond ONLY with JSON matching this schema:\n"
                + json.dumps(JUDGE_SCHEMA),
            },
            {
                "role": "user",
                "content": f"<document_a>\n{doc_a_md}\n</document_a>\n\n"
                f"<document_b>\n{doc_b_md}\n</document_b>",
            },
        ],
    )
    text = resp.choices[0].message.content or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"scores": None, "winner": "tie", "rationale": text[:2000]}

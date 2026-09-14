"""Thin LLM client layer over the model registry in config.MODELS.

complete()  -> generation via Anthropic or OpenAI-compatible (DeepSeek) SDK
judge_json() -> blind comparison scoring via DeepSeek JSON mode
"""
from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass

from app import config

MAX_TOKENS = 4096


class ModelUnavailable(RuntimeError):
    """The requested model's API key is not configured."""


def est_cost_usd(
    model_key: str, input_tokens: float | None, output_tokens: float | None
) -> float | None:
    """USD estimate from token counts × registry $/MTok prices (A/B scorecard)."""
    cfg = config.MODELS.get(model_key)
    if cfg is None or input_tokens is None or output_tokens is None:
        return None  # token columns are nullable on old document rows
    return (
        input_tokens * cfg["price_in"] + output_tokens * cfg["price_out"]
    ) / 1_000_000


@dataclass(frozen=True)
class GenResult:
    """One LLM call outcome: text plus usage for the UI/metrics."""

    text: str
    model_key: str
    input_tokens: int
    output_tokens: int
    latency_ms: int

    @property
    def est_cost_usd(self) -> float:
        return est_cost_usd(self.model_key, self.input_tokens, self.output_tokens)


def _require_key(model_key: str) -> dict:
    # Look up config.MODELS entry and ensure its API key env var is set.
    cfg = config.MODELS.get(model_key)
    if cfg is None:
        raise ModelUnavailable(f"unknown model: {model_key}")
    if not os.environ.get(cfg["key_env"]):
        raise ModelUnavailable(
            f"{cfg['label']} requires the {cfg['key_env']} environment variable"
        )
    return cfg


def _normalize_type_unions(node: dict) -> dict:
    """JSON Schema type arrays (e.g. ['integer', 'null']) -> anyOf for Anthropic."""
    out = copy.deepcopy(node)
    type_ = out.get("type")
    if isinstance(type_, list):
        out.pop("type")
        out["anyOf"] = [{"type": t} for t in type_]
    props = out.get("properties")
    if isinstance(props, dict):
        out["properties"] = {k: _normalize_type_unions(v) for k, v in props.items()}
    items = out.get("items")
    if isinstance(items, dict):
        out["items"] = _normalize_type_unions(items)
    for key in ("$defs", "definitions"):
        val = out.get(key)
        if isinstance(val, dict):
            out[key] = {k: _normalize_type_unions(v) for k, v in val.items()}
    for key in ("anyOf", "oneOf", "allOf"):
        val = out.get(key)
        if isinstance(val, list):
            out[key] = [_normalize_type_unions(v) for v in val]
    return out


def _anthropic_json_schema(json_schema: dict) -> dict:
    """Anthropic structured outputs reject minItems>1, maxItems, and type unions."""
    from anthropic import transform_schema  # lazy, like the SDK clients

    return transform_schema(_normalize_type_unions(json_schema))


def complete(
    model_key: str, system: str, user: str, json_schema: dict | None = None
) -> GenResult:
    """Write the report (or any structured completion). Routes Anthropic vs DeepSeek."""
    cfg = _require_key(model_key)
    t0 = time.perf_counter()
    if cfg["provider"] == "anthropic":
        # Claude path: native structured outputs when json_schema is set.
        import anthropic

        kwargs = {}
        if json_schema is not None:
            kwargs["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": _anthropic_json_schema(json_schema),
                }
            }
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=cfg["model"],
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{cfg['label']} refused the request")
        text = "".join(b.text for b in resp.content if b.type == "text")
        in_tok, out_tok = resp.usage.input_tokens, resp.usage.output_tokens
    else:  # openai_compat (DeepSeek)
        # DeepSeek path: OpenAI SDK + JSON mode; schema appended to system.
        from openai import OpenAI

        kwargs = {}
        if json_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
            system = (
                system
                + "\nRespond ONLY with JSON matching this schema:\n"
                + json.dumps(json_schema)
            )
        client = OpenAI(
            api_key=os.environ[cfg["key_env"]], base_url=cfg["base_url"]
        )
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
    # Blind A/B rubric: specificity, evidence, temporal_grounding, usefulness.
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
Judge only the content; ignore formatting differences. Never use em dashes or
en dashes in your rationale; use commas, colons, or periods instead."""

JUDGE_REFERENCE_NOTE = """
You are also given <source_material>: the community's actual posts from that
week. Treat it as ground truth. Claims consistent with it are evidence;
specific posts, events, or numbers it does not support are fabricated and
must drag down evidence and temporal_grounding, however confident they sound.
Do not reveal or guess which document had access to the source material."""


def judge_json(doc_a_md: str, doc_b_md: str, reference: str | None = None) -> dict:
    """Blind DeepSeek judge: A=baseline, B=RAG; optional source_material ground truth."""
    cfg = _require_key(config.DEFAULT_MODEL_KEY)
    from openai import OpenAI

    system = JUDGE_SYSTEM
    user = (
        f"<document_a>\n{doc_a_md}\n</document_a>\n\n"
        f"<document_b>\n{doc_b_md}\n</document_b>"
    )
    if reference:
        # Retrieved chunks from the RAG run, fabrications hurt evidence scores.
        system += JUDGE_REFERENCE_NOTE
        user = f"<source_material>\n{reference}\n</source_material>\n\n" + user
    client = OpenAI(api_key=os.environ[cfg["key_env"]], base_url=cfg["base_url"])
    resp = client.chat.completions.create(
        model=cfg["model"],
        max_tokens=1024,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": system
                + "\nRespond ONLY with JSON matching this schema:\n"
                + json.dumps(JUDGE_SCHEMA),
            },
            {"role": "user", "content": user},
        ],
    )
    text = resp.choices[0].message.content or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Soft fail: keep raw text so the A/B tab still has something to show.
        return {"scores": None, "winner": "tie", "rationale": text[:2000]}

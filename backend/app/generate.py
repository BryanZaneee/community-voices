"""Community Voices document generation and comparisons.

Retrieval: a fixed set of facet queries against the week's chunks (hybrid /
vector / bm25), stats bumped on every retrieved chunk. Generation: RAG
(context in prompt) or baseline (no context). Comparisons: rag_vs_baseline,
model_vs_model, retrieval_vs_retrieval — all judged by Claude Haiku.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable

from app import db, llm
from app.rag.retriever import RetrievalMode, Retriever

CANONICAL_QUERIES = [
    "biggest most popular posts and highlights this week",
    "debates, disagreements, and controversies",
    "questions people are asking and help requests",
    "tips, recommendations, and things worth playing",
    "upcoming releases, events, and announcements",
    "community mood, jokes, and running themes",
]
K_PER_QUERY = 8
MAX_CONTEXT_CHUNKS = 18

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "lede": {"type": "string"},
        "topics": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "share_pct": {"type": ["integer", "null"]},
                    "threads": {"type": ["integer", "null"]},
                },
                "required": ["name", "summary", "share_pct", "threads"],
                "additionalProperties": False,
            },
        },
        "standouts": {"type": "array", "items": {"type": "string"}},
        "prediction_review": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "prediction": {"type": "string"},
                    "grade": {"type": "string", "enum": ["hit", "partial", "miss"]},
                    "evidence": {"type": "string"},
                },
                "required": ["prediction", "grade", "evidence"],
                "additionalProperties": False,
            },
        },
        "predictions": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "confidence": {"type": "integer"},
                    "rationale": {"type": "string"},
                    "signals": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "confidence", "rationale", "signals"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "headline", "lede", "topics", "standouts",
        "prediction_review", "predictions",
    ],
    "additionalProperties": False,
}

DOC_SYSTEM = """You write a weekly "Community Voices" report for the online
community {community}, covering the week of {week_range}.

Respond with a single JSON object with these fields:
- headline: punchy 6-12 word title capturing the week
- lede: 2-3 sentence overview paragraph
- topics: 3-5 themes the community discussed. Each has: name, summary
  (3-4 concrete sentences), share_pct (your estimate of the theme's integer
  percentage share of the week's discussion; all topics together at most 100),
  threads (estimated thread count, or null if you cannot estimate)
- standouts: 3-5 one-sentence strings on individual notable posts
- prediction_review: {prediction_review_section}
- predictions: 3-5 forecasts for next week. Each has: title, confidence
  (integer 0-100), rationale (one sentence of reasoning based on observed
  momentum), signals (2-3 short strings naming the momentum you observed)

Write in an engaging, concrete style. Output JSON only."""

RAG_INSTRUCTIONS = """Ground every claim in the context below — cite post titles
in *italics* when referencing them. Do not invent posts or events. Base your
predictions on the momentum you observe in the context.

<context>
{context}
</context>"""

BASELINE_INSTRUCTIONS = """You have NO access to this week's actual discussions.
Using only your general knowledge of this community and gaming at large, write
your best guess at what was discussed and what comes next. Set share_pct and
threads to null — you cannot measure them. Do not invent specific post titles
or exact numbers; be honest, generalities are acceptable."""

PREDICTION_REVIEW = """grade last week's predictions — how did they hold up?
The previous week's document predicted:
{previous_predictions}
One entry per prediction: prediction (short restatement), grade (hit, partial,
or miss), evidence (one sentence grounded in this week's discussions)."""

NO_REVIEW = "null (there is no prior week's document to review)"


def build_markdown(community: str, week_range: str, report: dict) -> str:
    """Render the structured report as the exported markdown document.

    The first line and the section markers are load-bearing: tests pin the
    "# Community Voices" prefix, and _previous_predictions() slices prior
    docs at "## Predictions for next week".
    """
    lines = [f"# Community Voices — {community} — Week of {week_range}", ""]
    lines += [f"**{report['headline']}**", "", report["lede"], ""]
    lines.append("## What the community talked about")
    for t in report["topics"]:
        lines += ["", f"### {t['name']}"]
        meta = " · ".join(
            part
            for part, present in (
                (f"{t.get('share_pct')}% of discussion", t.get("share_pct") is not None),
                (f"{t.get('threads')} threads", t.get("threads") is not None),
            )
            if present
        )
        if meta:
            lines.append(f"_{meta}_")
        lines += ["", t["summary"]]
    lines += ["", "## Standout threads", ""]
    lines += [f"- {s}" for s in report["standouts"]]
    if report.get("prediction_review"):
        lines += ["", "## Last week's predictions — how did they hold up?", ""]
        lines += [
            f"- **{r['prediction']}** — {r['grade']}: {r['evidence']}"
            for r in report["prediction_review"]
        ]
    lines += ["", "## Predictions for next week"]
    for p in report["predictions"]:
        lines += ["", f"### {p['title']} — {p['confidence']}% confidence", ""]
        lines.append(p["rationale"])
        lines += [f"- {s}" for s in p["signals"]]
    return "\n".join(lines) + "\n"


def week_paths(conn: sqlite3.Connection, week_start: str) -> set[str]:
    return {row["id"] for row in db.posts_in_week(conn, week_start)}


def retrieve_context(
    conn: sqlite3.Connection,
    retriever: Retriever,
    week_start: str,
    mode: RetrievalMode = "hybrid",
) -> tuple[list, dict]:
    """Facet-query retrieval scoped to one week. Returns (chunks, meta)."""
    if mode in ("hybrid", "vector") and retriever.embedding is None:
        mode = "bm25"  # record the mode that actually ran
    allowed = week_paths(conn, week_start)
    best: dict[str, tuple[float, object]] = {}
    timings = []
    for query in CANONICAL_QUERIES:
        signals = retriever.search_with_signals(
            query, k=K_PER_QUERY, mode=mode, allowed_paths=allowed
        )
        timings.append(signals.timings)
        for r in signals.fused:
            prev = best.get(r.chunk.chunk_id)
            if prev is None or r.score > prev[0]:
                best[r.chunk.chunk_id] = (r.score, r.chunk)
    ranked = sorted(best.values(), key=lambda t: -t[0])[:MAX_CONTEXT_CHUNKS]
    chunks = [chunk for _, chunk in ranked]
    db.bump_stats(conn, [c.chunk_id for c in chunks])
    retrieval_ms = round(
        sum(t["embed_ms"] + t["bm25_ms"] + t["vector_ms"] for t in timings), 1
    )
    return chunks, {"retrieval_ms": retrieval_ms, "mode": mode}


def _post_meta(conn: sqlite3.Connection, post_ids: set[str]) -> dict[str, sqlite3.Row]:
    if not post_ids:
        return {}
    ph = ",".join("?" * len(post_ids))
    rows = conn.execute(f"SELECT * FROM posts WHERE id IN ({ph})", list(post_ids))
    return {r["id"]: r for r in rows}


def _context_block(conn: sqlite3.Connection, chunks: list) -> str:
    posts = _post_meta(conn, {c.path for c in chunks})
    parts = []
    for c in chunks:
        p = posts.get(c.path)
        header = (
            f'[title="{p["title"]}" score={p["score"]} comments={p["num_comments"]}]'
            if p
            else f"[post={c.path}]"
        )
        parts.append(f"{header}\n{c.content}")
    return "\n\n---\n\n".join(parts)


def _previous_predictions(
    conn: sqlite3.Connection, community: str, week_start: str
) -> str | None:
    """Predictions section of the newest RAG doc for the preceding week."""
    prev_start = (
        datetime.fromisoformat(week_start) - timedelta(days=7)
    ).date().isoformat()
    row = conn.execute(
        "SELECT content_md FROM documents WHERE subreddit = ? AND week_start = ? "
        "AND mode = 'rag' ORDER BY id DESC LIMIT 1",
        (community, prev_start),
    ).fetchone()
    if row is None:
        return None
    md = row["content_md"]
    marker = "## Predictions for next week"
    return md[md.index(marker):] if marker in md else None


def generate_document(
    conn: sqlite3.Connection,
    retriever: Retriever,
    *,
    week_start: str,
    mode: str,  # 'rag' | 'baseline'
    model_key: str,
    retrieval_mode: RetrievalMode = "hybrid",
    progress: Callable[[str, dict], None] | None = None,
) -> int:
    """Generate one document, store it, return documents.id.

    `progress(stage, info)` is called around the retrieve and write stages
    (used by the SSE endpoint); it must not raise."""
    emit = progress or (lambda stage, info: None)
    community = db.get_meta(conn, "subreddit") or "games@lemmy.world"
    week_end = (
        datetime.fromisoformat(week_start) + timedelta(days=7)
    ).date().isoformat()

    prev = _previous_predictions(conn, community, week_start)
    review = (
        PREDICTION_REVIEW.format(previous_predictions=prev) if prev else NO_REVIEW
    )
    week_range = f"{week_start} to {week_end}"
    system = DOC_SYSTEM.format(
        community=community,
        week_range=week_range,
        prediction_review_section=review,
    )

    chunks: list = []
    meta: dict = {}
    if mode == "rag":
        emit("retrieve", {"status": "start", "week_start": week_start})
        chunks, meta = retrieve_context(conn, retriever, week_start, retrieval_mode)
        if not chunks:
            raise ValueError(
                f"no chunks retrieved for week {week_start} "
                f"(retrieval_mode={meta['mode']}) — is the week ingested?"
            )
        emit(
            "retrieve",
            {
                "status": "end",
                "chunks": len(chunks),
                "mode": meta["mode"],
                "retrieval_ms": meta["retrieval_ms"],
            },
        )
        user = RAG_INSTRUCTIONS.format(context=_context_block(conn, chunks))
    else:
        user = BASELINE_INSTRUCTIONS

    emit("write", {"status": "start", "model_key": model_key})
    result = llm.complete(model_key, system, user, json_schema=REPORT_SCHEMA)
    emit(
        "write",
        {
            "status": "end",
            "latency_ms": result.latency_ms,
            "output_tokens": result.output_tokens,
        },
    )

    report_json = None
    try:
        report = json.loads(result.text)
        content_md = build_markdown(community, week_range, report)
        report_json = result.text
    except (json.JSONDecodeError, KeyError, TypeError):
        # Model ignored the schema — keep its raw text; the UI falls back to
        # rendering content_md directly.
        content_md = result.text

    with conn:
        cur = conn.execute(
            "INSERT INTO documents (mode, model_key, week_start, subreddit, "
            "  content_md, report_json, queries, retrieved_chunk_ids, "
            "  retrieval_mode, latency_ms, input_tokens, output_tokens) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mode,
                model_key,
                week_start,
                community,
                content_md,
                report_json,
                json.dumps(CANONICAL_QUERIES) if mode == "rag" else None,
                json.dumps([c.chunk_id for c in chunks]) if mode == "rag" else None,
                meta.get("mode") if mode == "rag" else None,
                result.latency_ms,
                result.input_tokens,
                result.output_tokens,
            ),
        )
    return cur.lastrowid


def _doc(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()


def run_comparison(
    conn: sqlite3.Connection,
    retriever: Retriever,
    *,
    kind: str,
    week_start: str,
    model_a: str,
    model_b: str | None = None,
    retrieval_a: RetrievalMode = "hybrid",
    retrieval_b: RetrievalMode = "bm25",
) -> int:
    """Generate both sides + judge, store, return comparisons.id."""
    if kind == "rag_vs_baseline":
        # A = baseline (no RAG), B = RAG — same model
        a_id = generate_document(
            conn, retriever, week_start=week_start, mode="baseline", model_key=model_a
        )
        b_id = generate_document(
            conn, retriever, week_start=week_start, mode="rag", model_key=model_a
        )
    elif kind == "model_vs_model":
        a_id = generate_document(
            conn, retriever, week_start=week_start, mode="rag", model_key=model_a
        )
        b_id = generate_document(
            conn, retriever, week_start=week_start, mode="rag",
            model_key=model_b or model_a,
        )
    elif kind == "retrieval_vs_retrieval":
        a_id = generate_document(
            conn, retriever, week_start=week_start, mode="rag",
            model_key=model_a, retrieval_mode=retrieval_a,
        )
        b_id = generate_document(
            conn, retriever, week_start=week_start, mode="rag",
            model_key=model_a, retrieval_mode=retrieval_b,
        )
    else:
        raise ValueError(f"unknown comparison kind: {kind}")

    doc_a, doc_b = _doc(conn, a_id), _doc(conn, b_id)
    judge = llm.judge_json(doc_a["content_md"], doc_b["content_md"])

    extra = None
    if kind == "retrieval_vs_retrieval":
        ids_a = set(json.loads(doc_a["retrieved_chunk_ids"] or "[]"))
        ids_b = set(json.loads(doc_b["retrieved_chunk_ids"] or "[]"))
        union = ids_a | ids_b
        extra = json.dumps(
            {
                "chunk_overlap_jaccard": round(len(ids_a & ids_b) / len(union), 3)
                if union
                else None,
                "chunks_a": len(ids_a),
                "chunks_b": len(ids_b),
            }
        )

    with conn:
        cur = conn.execute(
            "INSERT INTO comparisons (kind, doc_a_id, doc_b_id, judge_json, extra_json) "
            "VALUES (?,?,?,?,?)",
            (kind, a_id, b_id, json.dumps(judge), extra),
        )
    return cur.lastrowid

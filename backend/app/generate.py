"""Community Voices document generation and the RAG-vs-baseline comparison.

Retrieval: a fixed set of facet queries against the week's chunks (hybrid /
vector / bm25), stats bumped on every retrieved chunk. Generation: RAG
(context in prompt) or baseline (no context). Comparisons are judged blind.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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
                    "detail": {"type": "string"},
                    "share_pct": {"type": ["integer", "null"]},
                    "threads": {"type": ["integer", "null"]},
                },
                "required": ["name", "summary", "detail", "share_pct", "threads"],
                "additionalProperties": False,
            },
        },
        "standouts": {"type": "array", "items": {"type": "string"}},
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
    "required": ["headline", "lede", "topics", "standouts", "predictions"],
    "additionalProperties": False,
}

DOC_SYSTEM = """You write a weekly "Community Voices" report for the online
community {community}, covering the week of {week_range}.

Respond with a single JSON object with these fields:
- headline: punchy 6-12 word title capturing the week
- lede: 2-3 sentence overview paragraph
- topics: 3-5 themes the community discussed. Each has: name, summary
  (3-4 concrete sentences), detail (a deeper 4-6 sentence dive for readers
  who expand the topic — more threads, reactions, and specifics not already
  in the summary), share_pct (your estimate of the theme's integer
  percentage share of the week's discussion; all topics together at most 100),
  threads (estimated thread count, or null if you cannot estimate)
- standouts: 3-5 one-sentence strings on individual notable posts
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

def build_markdown(community: str, week_range: str, report: dict) -> str:
    """Render the structured report as the exported markdown document.
    Tests pin the "# Community Voices" first line."""
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
        if t.get("detail"):
            lines += ["", t["detail"]]
    lines += ["", "## Standout threads", ""]
    lines += [f"- {s}" for s in report["standouts"]]
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

    week_range = f"{week_start} to {week_end}"
    system = DOC_SYSTEM.format(community=community, week_range=week_range)

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


def _predictions_detail(doc_b: sqlite3.Row) -> str:
    try:
        preds = json.loads(doc_b["report_json"])["predictions"]
        avg = round(sum(p["confidence"] for p in preds) / len(preds))
        return f"{len(preds)} forecasts · avg {avg}% confidence"
    except (TypeError, KeyError, ValueError, ZeroDivisionError):
        return "forecasts drafted"


def _reference_block(conn: sqlite3.Connection, doc_b: sqlite3.Row) -> str | None:
    """The RAG doc's actual retrieved chunks, formatted like its prompt
    context — ground truth for the judge to grade both docs against."""
    ids = json.loads(doc_b["retrieved_chunk_ids"] or "null") or []
    if not ids:
        return None
    ph = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT path, content FROM chunks WHERE chunk_id IN ({ph})", ids
    ).fetchall()
    chunks = [SimpleNamespace(path=r["path"], content=r["content"]) for r in rows]
    return _context_block(conn, chunks) if chunks else None


def _judge_detail(judge: dict) -> str:
    winner = {"a": "baseline", "b": "RAG"}.get(judge.get("winner"), "tie")
    scores = judge.get("scores")
    if not scores:
        return f"winner: {winner}"
    return (
        f"winner: {winner} · RAG {sum(scores['b'].values())}"
        f" vs baseline {sum(scores['a'].values())} / 20"
    )


def run_comparison(
    conn: sqlite3.Connection,
    retriever: Retriever,
    *,
    week_start: str,
    model_key: str,
    progress: Callable[[str, dict], None] | None = None,
    on_ready: Callable[[int], None] | None = None,
) -> tuple[int | None, int]:
    """RAG-vs-baseline: generate both sides + judge, store, return
    (comparison id, RAG doc id). A = baseline (no RAG), B = RAG — same model.

    The RAG doc is generated first; if the baseline or judge then fails, no
    comparison row is stored and the id comes back None — the caller still
    has a finished report to show. `on_ready(rag_doc_id)` fires once as soon
    as the report is deliverable (both drafts done, judge still deciding) so
    the SSE endpoint can hand the report over while judging continues."""
    emit = progress or (lambda stage, info: None)
    ready_sent = False

    def ready(b_id: int) -> None:
        nonlocal ready_sent
        if on_ready and not ready_sent:
            ready_sent = True
            on_ready(b_id)
    b_id = generate_document(
        conn,
        retriever,
        week_start=week_start,
        mode="rag",
        model_key=model_key,
        progress=progress,
    )
    doc_b = _doc(conn, b_id)
    emit("predict", {"status": "end", "detail": _predictions_detail(doc_b)})

    def baseline_progress(stage: str, info: dict) -> None:
        if stage != "write":
            return
        if info.get("status") == "start":
            emit("ab", {"status": "start",
                        "detail": "baseline draft · no retrieval · same model"})
        else:
            emit("ab", {"status": "end",
                        "detail": f"baseline · {info.get('latency_ms')} ms · "
                                  f"{info.get('output_tokens')} tok"})

    try:
        a_id = generate_document(
            conn,
            retriever,
            week_start=week_start,
            mode="baseline",
            model_key=model_key,
            progress=baseline_progress,
        )
        doc_a = _doc(conn, a_id)
        ready(b_id)
        emit("evaluate", {"status": "start",
                          "detail": "blind judge · 4 criteria · graded "
                                    "against the week's source material"})
        judge = llm.judge_json(
            doc_a["content_md"],
            doc_b["content_md"],
            reference=_reference_block(conn, doc_b),
        )
        emit("evaluate", {"status": "end", "detail": _judge_detail(judge)})
    except Exception as exc:
        if progress is None:
            raise
        ready(b_id)
        emit("evaluate", {"status": "end", "detail": f"comparison skipped: {exc}"})
        return None, b_id
    with conn:
        cur = conn.execute(
            "INSERT INTO comparisons (kind, doc_a_id, doc_b_id, judge_json) "
            "VALUES ('rag_vs_baseline',?,?,?)",
            (a_id, b_id, json.dumps(judge)),
        )
    return cur.lastrowid, b_id

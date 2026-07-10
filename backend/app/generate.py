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

DOC_SYSTEM = """You write a weekly "Community Voices" document for an online community.
Structure it exactly as:

# Community Voices — {community} — Week of {week_range}

## What the community talked about
3-5 themes, each a short paragraph.

## Standout threads
3-5 bullet points on individual notable posts.
{prediction_review_section}
## Predictions for next week
3-5 predictions with one sentence of reasoning each, based on observed momentum.

Write in an engaging, concrete style. Markdown only, no preamble."""

RAG_INSTRUCTIONS = """Ground every claim in the context below — cite post titles
in *italics* when referencing them. Do not invent posts or events. Base your
predictions on the momentum you observe in the context.

<context>
{context}
</context>"""

BASELINE_INSTRUCTIONS = """You have NO access to this week's actual discussions.
Using only your general knowledge of this community and gaming at large, write
your best guess at what was discussed and what comes next. Do not invent
specific post titles or exact numbers; be honest generalities are acceptable."""

PREDICTION_REVIEW = """
## Last week's predictions — how did they hold up?
The previous week's document predicted:
{previous_predictions}
Grade each prediction against this week's actual discussions (hit / partial / miss)
with one sentence of evidence each.
"""


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
) -> int:
    """Generate one document, store it, return documents.id."""
    community = db.get_meta(conn, "subreddit") or "games@lemmy.world"
    week_end = (
        datetime.fromisoformat(week_start) + timedelta(days=7)
    ).date().isoformat()

    prev = _previous_predictions(conn, community, week_start)
    review = PREDICTION_REVIEW.format(previous_predictions=prev) if prev else ""
    system = DOC_SYSTEM.format(
        community=community,
        week_range=f"{week_start} to {week_end}",
        prediction_review_section=review,
    )

    chunks: list = []
    meta: dict = {}
    if mode == "rag":
        chunks, meta = retrieve_context(conn, retriever, week_start, retrieval_mode)
        if not chunks:
            raise ValueError(
                f"no chunks retrieved for week {week_start} "
                f"(retrieval_mode={meta['mode']}) — is the week ingested?"
            )
        user = RAG_INSTRUCTIONS.format(context=_context_block(conn, chunks))
    else:
        user = BASELINE_INSTRUCTIONS

    result = llm.complete(model_key, system, user)

    with conn:
        cur = conn.execute(
            "INSERT INTO documents (mode, model_key, week_start, subreddit, "
            "  content_md, queries, retrieved_chunk_ids, retrieval_mode, "
            "  latency_ms, input_tokens, output_tokens) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                mode,
                model_key,
                week_start,
                community,
                result.text,
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

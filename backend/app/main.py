"""FastAPI app: JSON API + static SPA mount.

Read endpoints never require API keys. Generation endpoints check the
requested model's key; the live week pull checks the Voyage + Reddit keys.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import config, db, generate, ingest, llm
from app.rag.embeddings import VoyageEmbeddingProvider
from app.rag.retriever import RetrievalMode, Retriever
from app.rag.vector_index import VectorIndex

state: dict = {}


def _build_retriever(conn: sqlite3.Connection, vector_index: VectorIndex) -> Retriever:
    provider = None
    if os.environ.get("VOYAGE_API_KEY"):
        provider = VoyageEmbeddingProvider(model=config.EMBEDDING_MODEL)
    return Retriever(
        embedding_provider=provider,
        bm25_index=db.build_bm25(conn),
        vector_index=vector_index,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect(config.DB_PATH)
    vector_index = VectorIndex(config.DB_PATH, dim=config.EMBEDDING_DIM)
    vector_index.ensure_schema()
    state["conn"] = conn
    state["vector_index"] = vector_index
    state["retriever"] = _build_retriever(conn, vector_index)
    yield
    conn.close()
    vector_index.close()


app = FastAPI(title="Community Voices", lifespan=lifespan)


def _row_to_doc(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("queries", "retrieved_chunk_ids"):
        if d.get(key):
            d[key] = json.loads(d[key])
    return d


@app.get("/api/status")
def status() -> dict:
    conn = state["conn"]
    return {
        "subreddit": db.get_meta(conn, "subreddit"),
        "ingested_at": db.get_meta(conn, "ingested_at"),
        "embedding_model": db.get_meta(conn, "embedding_model"),
        "weeks": db.week_windows(conn),
        "hybrid": state["retriever"].embedding is not None,
        "can_pull_live": bool(os.environ.get("VOYAGE_API_KEY"))
        and (
            (db.get_meta(conn, "source") or "lemmy") != "reddit"
            or bool(
                os.environ.get("REDDIT_CLIENT_ID")
                and os.environ.get("REDDIT_CLIENT_SECRET")
            )
        ),
        "models_available": config.available_models(),
        "models": {
            key: {"label": cfg["label"], "vendor": cfg["vendor"]}
            for key, cfg in config.MODELS.items()
        },
    }


class GenerateBody(BaseModel):
    week_start: str
    mode: Literal["rag", "baseline"] = "rag"
    model_key: str
    retrieval_mode: RetrievalMode = "hybrid"


@app.post("/api/generate")
def generate_endpoint(body: GenerateBody) -> dict:
    try:
        doc_id = generate.generate_document(
            state["conn"],
            state["retriever"],
            week_start=body.week_start,
            mode=body.mode,
            model_key=body.model_key,
            retrieval_mode=body.retrieval_mode,
        )
    except (llm.ModelUnavailable, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return _row_to_doc(
        state["conn"].execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    )


class CompareBody(BaseModel):
    week_start: str
    kind: Literal["rag_vs_baseline", "model_vs_model", "retrieval_vs_retrieval"]
    model_a: str
    model_b: str | None = None
    retrieval_a: RetrievalMode = "hybrid"
    retrieval_b: RetrievalMode = "bm25"


@app.post("/api/compare")
def compare_endpoint(body: CompareBody) -> dict:
    try:
        comp_id = generate.run_comparison(
            state["conn"],
            state["retriever"],
            kind=body.kind,
            week_start=body.week_start,
            model_a=body.model_a,
            model_b=body.model_b,
            retrieval_a=body.retrieval_a,
            retrieval_b=body.retrieval_b,
        )
    except (llm.ModelUnavailable, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return _comparison(comp_id)


def _comparison(comp_id: int) -> dict:
    conn = state["conn"]
    row = conn.execute(
        "SELECT * FROM comparisons WHERE id = ?", (comp_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "comparison not found")
    return {
        "id": row["id"],
        "kind": row["kind"],
        "created_at": row["created_at"],
        "doc_a": _row_to_doc(
            conn.execute(
                "SELECT * FROM documents WHERE id = ?", (row["doc_a_id"],)
            ).fetchone()
        ),
        "doc_b": _row_to_doc(
            conn.execute(
                "SELECT * FROM documents WHERE id = ?", (row["doc_b_id"],)
            ).fetchone()
        ),
        "judge": json.loads(row["judge_json"]) if row["judge_json"] else None,
        "extra": json.loads(row["extra_json"]) if row["extra_json"] else None,
    }


@app.get("/api/comparisons/latest")
def latest_comparison(kind: str | None = None) -> dict:
    conn = state["conn"]
    sql = "SELECT id FROM comparisons"
    args: tuple = ()
    if kind:
        sql += " WHERE kind = ?"
        args = (kind,)
    row = conn.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()
    if row is None:
        raise HTTPException(404, "no comparisons yet")
    return _comparison(row["id"])


@app.get("/api/documents")
def list_documents(week_start: str | None = None, limit: int = 20) -> list[dict]:
    conn = state["conn"]
    sql = "SELECT * FROM documents"
    args: list = []
    if week_start:
        sql += " WHERE week_start = ?"
        args.append(week_start)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(min(limit, 100))
    return [_row_to_doc(r) for r in conn.execute(sql, args).fetchall()]


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: int) -> dict:
    row = state["conn"].execute(
        "SELECT * FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "document not found")
    return _row_to_doc(row)


@app.get("/api/documents/{doc_id}/download")
def download_document(doc_id: int) -> Response:
    row = state["conn"].execute(
        "SELECT * FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "document not found")
    name = f"community-voices-{row['subreddit']}-{row['week_start']}-{row['mode']}.md"
    return Response(
        content=row["content_md"],
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/ingest/week")
def ingest_week() -> dict:
    if not os.environ.get("VOYAGE_API_KEY"):
        raise HTTPException(400, "Live pull requires VOYAGE_API_KEY in .env")
    conn = state["conn"]
    source = db.get_meta(conn, "source") or "lemmy"
    if source == "reddit" and not (
        os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")
    ):
        raise HTTPException(
            400,
            "Reddit live pull requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET "
            "in .env (free script app: reddit.com/prefs/apps)",
        )
    community = (db.get_meta(conn, "subreddit") or config.DEFAULT_COMMUNITY).split("@")[0].removeprefix("r/")
    provider = VoyageEmbeddingProvider(model=config.EMBEDDING_MODEL)
    report = ingest.run_ingest(
        conn, state["vector_index"], provider, community,
        window="week", pages=1, source=source,
    )
    # BM25 is in-memory — rebuild so new chunks are searchable immediately
    state["retriever"] = _build_retriever(conn, state["vector_index"])
    return {"report": report, "weeks": db.week_windows(conn)}


@app.get("/api/embeddings")
def embeddings() -> dict:
    conn = state["conn"]
    pca_raw = db.get_meta(conn, "pca")
    if not pca_raw:
        return {"points": []}
    pca = json.loads(pca_raw)
    stats = {
        r["chunk_id"]: r["retrieved_count"]
        for r in conn.execute("SELECT chunk_id, retrieved_count FROM retrieval_stats")
    }
    posts = {
        r["id"]: {"title": r["title"], "created_utc": r["created_utc"]}
        for r in conn.execute("SELECT id, title, created_utc FROM posts")
    }
    weeks = db.week_windows(conn)

    def week_of(created_utc: float | None) -> str | None:
        if created_utc is None:
            return None
        from datetime import datetime, timedelta, timezone

        for w in weeks:
            start = datetime.fromisoformat(w["week_start"]).replace(
                tzinfo=timezone.utc
            )
            end = start + timedelta(days=7)
            if start.timestamp() <= created_utc < end.timestamp():
                return w["week_start"]
        return None

    points = []
    for p in pca["points"]:
        post = posts.get(p["path"], {})
        points.append(
            {
                **p,
                "title": post.get("title"),
                "week_start": week_of(post.get("created_utc")),
                "retrieved_count": stats.get(p["id"], 0),
            }
        )
    return {"embedding_model": pca.get("embedding_model"), "points": points}


@app.get("/api/stats")
def stats() -> dict:
    conn = state["conn"]
    totals = conn.execute(
        "SELECT COALESCE(SUM(retrieved_count), 0) AS total, "
        "COUNT(*) AS chunks_retrieved FROM retrieval_stats"
    ).fetchone()
    n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    top = conn.execute(
        "SELECT s.chunk_id, s.retrieved_count, s.last_retrieved_at, "
        "  c.path, c.heading_path, substr(c.content, 1, 220) AS snippet, p.title "
        "FROM retrieval_stats s "
        "JOIN chunks c ON c.chunk_id = s.chunk_id "
        "LEFT JOIN posts p ON p.id = c.path "
        "ORDER BY s.retrieved_count DESC, s.last_retrieved_at DESC LIMIT 25"
    ).fetchall()
    per_model = conn.execute(
        "SELECT model_key, COUNT(*) AS docs, ROUND(AVG(latency_ms)) AS avg_latency_ms, "
        "  ROUND(AVG(input_tokens)) AS avg_input_tokens, "
        "  ROUND(AVG(output_tokens)) AS avg_output_tokens "
        "FROM documents GROUP BY model_key ORDER BY docs DESC"
    ).fetchall()
    return {
        "total_retrievals": totals["total"],
        "chunks_total": n_chunks,
        "chunks_never_retrieved": n_chunks - totals["chunks_retrieved"],
        "top_chunks": [dict(r) for r in top],
        "per_model": [dict(r) for r in per_model],
    }


if config.FRONTEND_DIST.is_dir():
    app.mount(
        "/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="spa"
    )

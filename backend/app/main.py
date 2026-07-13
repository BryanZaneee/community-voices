"""FastAPI app: JSON API + static SPA mount.

Read endpoints never require API keys. Generation endpoints check the
model's key; the live week pull checks the Voyage key.
"""
from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
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
    for key in ("queries", "retrieved_chunk_ids", "report_json"):
        if d.get(key):
            d[key] = json.loads(d[key])
    cost = llm.est_cost_usd(d["model_key"], d["input_tokens"], d["output_tokens"])
    d["cost_usd"] = round(cost, 4) if cost is not None else None
    return d


def read_conn():
    """Fresh connection per read request. The single lifespan connection is
    reserved for the mutating endpoints; sharing it across FastAPI's
    request threadpool raced sqlite's statement cache under concurrent
    page-load reads (InterfaceError)."""
    conn = db.connect(config.DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/api/status")
def status(conn: sqlite3.Connection = Depends(read_conn)) -> dict:
    weeks = db.week_windows(conn)
    ingest_report = db.get_meta(conn, "ingest_report")
    return {
        "subreddit": db.get_meta(conn, "subreddit"),
        "source": db.get_meta(conn, "source") or "lemmy",
        "ingested_at": db.get_meta(conn, "ingested_at"),
        "embedding_model": db.get_meta(conn, "embedding_model"),
        "embedding_dim": db.get_meta(conn, "embedding_dim"),
        "weeks": weeks,
        "activity": db.daily_post_counts(conn),
        "week_totals": db.week_totals(conn, weeks[0]["week_start"]) if weeks else None,
        "chunks_total": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "last_ingest": json.loads(ingest_report) if ingest_report else None,
        "hybrid": state["retriever"].embedding is not None,
        "can_pull_live": bool(os.environ.get("VOYAGE_API_KEY")),
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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _cached_stage_events(conn: sqlite3.Connection, week_start: str) -> list[str]:
    """The crawl/reduce/embed stages ran at ingest time — report their real
    cached facts instantly so the pipeline UI stays honest."""
    week = next(
        (w for w in db.week_windows(conn) if w["week_start"] == week_start), None
    )
    n_posts = week["n_posts"] if week else 0
    n_chunks = week["n_chunks"] if week else 0
    model = db.get_meta(conn, "embedding_model") or config.EMBEDDING_MODEL
    ingested = db.get_meta(conn, "ingested_at") or "unknown"
    return [
        _sse("stage", {"stage": "crawl", "status": "cached",
                       "detail": f"{n_posts} posts · ingested {ingested}"}),
        _sse("stage", {"stage": "reduce", "status": "cached",
                       "detail": f"{n_posts} posts → {n_chunks} chunks"}),
        _sse("stage", {"stage": "embed", "status": "cached",
                       "detail": f"{n_chunks} chunks · {model} · sqlite-vec"}),
    ]


@app.get("/api/generate/stream")
def generate_stream(
    week_start: str,
    model_key: str,
    mode: Literal["rag", "baseline"] = "rag",
    retrieval_mode: RetrievalMode = "hybrid",
) -> StreamingResponse:
    """SSE variant of /api/generate: stage events, then `done` with the Doc."""
    conn = state["conn"]
    q: queue.Queue = queue.Queue()

    def progress(stage: str, info: dict) -> None:
        q.put(_sse("stage", {"stage": stage, **info}))

    def run() -> None:
        try:
            doc_id = generate.generate_document(
                conn,
                state["retriever"],
                week_start=week_start,
                mode=mode,
                model_key=model_key,
                retrieval_mode=retrieval_mode,
                progress=progress,
            )
            doc = _row_to_doc(
                conn.execute(
                    "SELECT * FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
            )
            q.put(_sse("done", doc))
        except Exception as exc:  # surfaced to the client as an SSE event
            q.put(_sse("error", {"detail": str(exc)}))
        finally:
            q.put(None)

    def events():
        yield from _cached_stage_events(conn, week_start)
        # ponytail: one worker thread per stream, UI serializes runs; a job
        # queue is the upgrade path if generation ever goes multi-user.
        threading.Thread(target=run, daemon=True).start()
        while (item := q.get()) is not None:
            yield item

    return StreamingResponse(events(), media_type="text/event-stream")


class CompareBody(BaseModel):
    week_start: str
    model_key: str


@app.post("/api/compare")
def compare_endpoint(body: CompareBody) -> dict:
    """RAG vs baseline — the only comparison kind."""
    try:
        comp_id = generate.run_comparison(
            state["conn"],
            state["retriever"],
            week_start=body.week_start,
            model_key=body.model_key,
        )
    except (llm.ModelUnavailable, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return _comparison(comp_id, state["conn"])


def _comparison(comp_id: int, conn: sqlite3.Connection) -> dict:
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
def latest_comparison(
    kind: str | None = None, conn: sqlite3.Connection = Depends(read_conn)
) -> dict:
    sql = "SELECT id FROM comparisons"
    args: tuple = ()
    if kind:
        sql += " WHERE kind = ?"
        args = (kind,)
    row = conn.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()
    if row is None:
        raise HTTPException(404, "no comparisons yet")
    return _comparison(row["id"], conn)


@app.get("/api/documents")
def list_documents(
    week_start: str | None = None,
    limit: int = 20,
    conn: sqlite3.Connection = Depends(read_conn),
) -> list[dict]:
    sql = "SELECT * FROM documents"
    args: list = []
    if week_start:
        sql += " WHERE week_start = ?"
        args.append(week_start)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(min(limit, 100))
    return [_row_to_doc(r) for r in conn.execute(sql, args).fetchall()]


@app.get("/api/documents/{doc_id}")
def get_document(
    doc_id: int, conn: sqlite3.Connection = Depends(read_conn)
) -> dict:
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "document not found")
    return _row_to_doc(row)


@app.get("/api/documents/{doc_id}/download")
def download_document(
    doc_id: int, conn: sqlite3.Connection = Depends(read_conn)
) -> Response:
    row = conn.execute(
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
    community = (db.get_meta(conn, "subreddit") or config.DEFAULT_COMMUNITY).split("@")[0]
    provider = VoyageEmbeddingProvider(model=config.EMBEDDING_MODEL)
    report = ingest.run_ingest(
        conn, state["vector_index"], provider, community, window="week", pages=1,
    )
    # BM25 is in-memory — rebuild so new chunks are searchable immediately
    state["retriever"] = _build_retriever(conn, state["vector_index"])
    return {"report": report, "weeks": db.week_windows(conn)}


@app.get("/api/embeddings")
def embeddings(conn: sqlite3.Connection = Depends(read_conn)) -> dict:
    pca_raw = db.get_meta(conn, "pca")
    if not pca_raw:
        return {"points": []}
    pca = json.loads(pca_raw)
    stats = {
        r["chunk_id"]: r["retrieved_count"]
        for r in conn.execute("SELECT chunk_id, retrieved_count FROM retrieval_stats")
    }
    snippets = {
        r["chunk_id"]: r["snippet"]
        for r in conn.execute(
            "SELECT chunk_id, substr(content, 1, 180) AS snippet FROM chunks"
        )
    }
    posts = {
        r["id"]: {"title": r["title"], "created_utc": r["created_utc"]}
        for r in conn.execute("SELECT id, title, created_utc FROM posts")
    }
    windows = []
    for w in db.week_windows(conn):
        start = datetime.fromisoformat(w["week_start"]).replace(tzinfo=timezone.utc)
        end = start + timedelta(days=7)
        windows.append((start.timestamp(), end.timestamp(), w["week_start"]))

    def week_of(created_utc: float | None) -> str | None:
        if created_utc is None:
            return None
        for start_ts, end_ts, label in windows:
            if start_ts <= created_utc < end_ts:
                return label
        return None

    points = []
    for p in pca["points"]:
        post = posts.get(p["path"], {})
        points.append(
            {
                **p,
                "title": post.get("title"),
                "snippet": snippets.get(p["id"]),
                "week_start": week_of(post.get("created_utc")),
                "retrieved_count": stats.get(p["id"], 0),
            }
        )
    return {
        "embedding_model": pca.get("embedding_model"),
        "method": pca.get("method", "pca"),
        "clusters": pca.get("clusters", []),
        "points": points,
    }


@app.get("/api/stats")
def stats(conn: sqlite3.Connection = Depends(read_conn)) -> dict:
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
    return {
        "total_retrievals": totals["total"],
        "chunks_total": n_chunks,
        "chunks_never_retrieved": n_chunks - totals["chunks_retrieved"],
        "top_chunks": [dict(r) for r in top],
    }


if config.FRONTEND_DIST.is_dir():
    app.mount(
        "/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="spa"
    )

"""Offline end-to-end test: the whole product story in one flow.

ingest -> retrieve -> generate weekly docs oldest-first (prediction chain)
-> one comparison of each kind -> the API serves a consistent picture of it
all. Embeddings are fake, LLM calls stubbed; no network, no keys.
"""
import json

from fastapi.testclient import TestClient

from app import config, db, generate, ingest
from app import main as app_main
from app.rag.embeddings import FakeEmbeddingProvider
from app.rag.retriever import Retriever
from app.rag.vector_index import VectorIndex

from tests.conftest import DIM, make_posts


def test_full_pipeline_end_to_end(tmp_path, monkeypatch, keyless, stub_llm):
    db_path = tmp_path / "e2e.sqlite"

    # 1. Ingest a synthetic month
    conn = db.connect(db_path)
    vec = VectorIndex(db_path, dim=DIM)
    provider = FakeEmbeddingProvider(dim=DIM)
    posts, comments = make_posts(n=16, weeks=3)
    report = ingest.ingest_posts(conn, "test-community", posts, comments, provider, vec)
    assert report["chunks_new"] > 0

    # 2. Generate weekly docs oldest-first so predictions chain forward
    retriever = Retriever(
        embedding_provider=provider, bm25_index=db.build_bm25(conn), vector_index=vec
    )
    weeks = sorted(w["week_start"] for w in db.week_windows(conn))
    assert len(weeks) >= 2
    for week in weeks:
        generate.generate_document(
            conn, retriever, week_start=week, mode="rag", model_key="deepseek-v4"
        )
    # every doc after the first saw the prior week's predictions in its prompt
    systems = [c["system"] for c in stub_llm["complete"]]
    assert "how did they hold up" not in systems[0]
    assert all("how did they hold up" in s for s in systems[1:])
    assert all("Prediction alpha" in s for s in systems[1:])

    # 3. One comparison of each kind on the newest week
    newest = weeks[-1]
    for kind, kwargs in [
        ("rag_vs_baseline", {}),
        ("model_vs_model", {"model_b": "deepseek-v4-flash"}),
        ("retrieval_vs_retrieval", {}),
    ]:
        generate.run_comparison(
            conn, retriever, kind=kind, week_start=newest,
            model_a="deepseek-v4", **kwargs,
        )

    n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    total_bumps = conn.execute(
        "SELECT SUM(retrieved_count) FROM retrieval_stats"
    ).fetchone()[0]
    rag_docs = conn.execute(
        "SELECT retrieved_chunk_ids FROM documents WHERE mode = 'rag'"
    ).fetchall()
    expected_bumps = sum(len(json.loads(r[0])) for r in rag_docs)
    assert total_bumps == expected_bumps  # every retrieval was counted exactly once
    conn.close()
    vec.close()

    # 4. Boot the API on the same database and check the story is consistent
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "EMBEDDING_DIM", DIM)
    with TestClient(app_main.app) as client:
        status = client.get("/api/status").json()
        assert [w["week_start"] for w in status["weeks"]] == sorted(weeks, reverse=True)

        docs = client.get("/api/documents?limit=100").json()
        assert len(docs) == n_docs

        for kind in ("rag_vs_baseline", "model_vs_model", "retrieval_vs_retrieval"):
            comp = client.get(f"/api/comparisons/latest?kind={kind}").json()
            assert comp["judge"]["winner"] in ("a", "b", "tie")

        points = client.get("/api/embeddings").json()["points"]
        n_chunks = status_chunks = sum(w["n_chunks"] for w in status["weeks"])
        assert len(points) == n_chunks == status_chunks

        stats = client.get("/api/stats").json()
        assert stats["total_retrievals"] == total_bumps
        assert stats["chunks_total"] == n_chunks

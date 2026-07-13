"""API tests: every endpoint via FastAPI TestClient, fully offline."""
import json


def test_status_shape(client):
    d = client.get("/api/status").json()
    assert d["subreddit"] == "test-community"
    assert len(d["weeks"]) >= 2
    assert {"week_start", "week_end", "n_posts", "n_comments", "n_chunks"} <= set(
        d["weeks"][0]
    )
    assert d["hybrid"] is False  # keyless fixture
    assert d["can_pull_live"] is False
    assert {"deepseek-v4", "deepseek-v4-flash", "claude-opus-4-8", "claude-sonnet-5"} <= set(
        d["models"]
    )
    assert d["models_available"] == []  # keyless
    assert {s["key"] for s in d["sources"]} >= {"hackernews"}
    # sidebar identity-card fields
    assert len(d["activity"]) == 14
    assert sum(a["n_posts"] for a in d["activity"]) > 0
    assert d["week_totals"]["n_posts"] == d["weeks"][0]["n_posts"]
    assert d["week_totals"]["n_comments"] > 0
    assert d["chunks_total"] > 0
    assert d["source"] == "lemmy"  # default when never set


def _week(client) -> str:
    return client.get("/api/status").json()["weeks"][0]["week_start"]


def _generate(client, **overrides):
    body = {"week_start": _week(client), "mode": "rag", "model_key": "deepseek-v4"}
    body.update(overrides)
    return client.post("/api/generate", json=body)


def test_generate_and_document_endpoints(client):
    resp = _generate(client)
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["mode"] == "rag" and doc["retrieval_mode"] == "bm25"  # keyless
    assert isinstance(doc["retrieved_chunk_ids"], list)
    assert doc["cost_usd"] > 0  # derived from tokens x registry prices

    listed = client.get("/api/documents").json()
    assert any(d["id"] == doc["id"] for d in listed)
    filtered = client.get(f"/api/documents?week_start={doc['week_start']}").json()
    assert all(d["week_start"] == doc["week_start"] for d in filtered)

    single = client.get(f"/api/documents/{doc['id']}")
    assert single.status_code == 200
    assert client.get("/api/documents/99999").status_code == 404


def test_download_headers(client):
    doc = _generate(client).json()
    resp = client.get(f"/api/documents/{doc['id']}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.text.startswith("# Community Voices")
    assert client.get("/api/documents/99999/download").status_code == 404


def test_generate_error_paths(client):
    assert _generate(client, model_key="nope").status_code == 400
    resp = _generate(client, week_start="1999-01-01")
    assert resp.status_code == 400
    assert "no chunks" in resp.json()["detail"]


def test_compare_and_latest(client):
    week = _week(client)
    resp = client.post(
        "/api/compare",
        json={"week_start": week, "model_key": "deepseek-v4"},
    )
    assert resp.status_code == 200
    comp = resp.json()
    assert comp["kind"] == "rag_vs_baseline"
    assert comp["judge"]["winner"] in ("a", "b", "tie")
    assert comp["doc_a"]["mode"] == "baseline" and comp["doc_b"]["mode"] == "rag"
    assert comp["doc_a"]["content_md"].startswith("# Community Voices")

    latest = client.get("/api/comparisons/latest?kind=rag_vs_baseline").json()
    assert latest["id"] == comp["id"]
    assert client.get("/api/comparisons/latest?kind=other").status_code == 404


def test_generate_stream_events(client):
    week = _week(client)
    with client.stream(
        "GET",
        f"/api/generate/stream?week_start={week}&model_key=deepseek-v4",
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    stages = [
        json.loads(line[len("data: "):])["stage"]
        for line in body.splitlines()
        if line.startswith("data: ") and '"stage"' in line
    ]
    # cached ingest stages first, then the live pipeline incl. the A/B run
    assert stages[:3] == ["crawl", "reduce", "embed"]
    for live in ("retrieve", "write", "predict", "ab", "evaluate"):
        assert live in stages
    assert "event: done" in body
    # report is delivered before the judge finishes; verdict arrives last
    assert body.index("event: done") < body.index('"stage": "evaluate"')
    comp = json.loads(body.split("event: comparison\ndata: ")[1].split("\n")[0])
    assert comp["kind"] == "rag_vs_baseline" and comp["judge"]["winner"]
    done = json.loads(body.split("event: done\ndata: ")[1].split("\n")[0])
    assert done["week_start"] == week
    assert done["content_md"].startswith("# Community Voices")
    assert client.get(f"/api/documents/{done['id']}").status_code == 200


def _backdate_ingest(app_main, when="2026-07-01T06:00:00+00:00"):
    from app import db as _db

    _db.set_meta(app_main.state["conn"], "ingested_at", when)


def test_generate_stream_live_pull(client, monkeypatch):
    """With a Voyage key, a RAG stream runs a trailing-7-day pull first so
    the model writes from fresh data; the crawl/reduce/embed stages report
    the pull's real numbers instead of the cached ingest facts."""
    from app import main as app_main
    from app.rag.embeddings import FakeEmbeddingProvider

    from tests.conftest import DIM

    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
    monkeypatch.setattr(
        app_main, "VoyageEmbeddingProvider",
        lambda model: FakeEmbeddingProvider(dim=DIM),
    )
    _backdate_ingest(app_main)  # fixture ingested just now, which would skip
    pulls = []

    def fake_run_ingest(conn, vec, provider, community, window, pages, source):
        pulls.append({"community": community, "window": window, "source": source})
        return {"posts": 3, "comments": 7, "chunks_total": 9, "chunks_new": 2,
                "comment_fetches": 3, "fetch_s": 0.1, "index_s": 0.2}

    monkeypatch.setattr(app_main.ingest, "run_ingest", fake_run_ingest)

    week = _week(client)
    with client.stream(
        "GET",
        f"/api/generate/stream?week_start={week}&model_key=deepseek-v4",
    ) as resp:
        body = "".join(resp.iter_text())

    assert pulls == [
        {"community": "test-community", "window": "week", "source": "lemmy"}
    ]
    assert "live pull" in body
    assert "2 new chunks embedded" in body
    assert "event: done" in body


def test_generate_stream_live_pull_failure_degrades(client, monkeypatch):
    """A failed live pull must not kill generation — the stored corpus
    still produces the report."""
    from app import main as app_main

    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
    _backdate_ingest(app_main)

    def boom(*args, **kwargs):
        raise RuntimeError("lemmy.world unreachable")

    monkeypatch.setattr(app_main, "_live_pull", boom)
    week = _week(client)
    with client.stream(
        "GET",
        f"/api/generate/stream?week_start={week}&model_key=deepseek-v4",
    ) as resp:
        body = "".join(resp.iter_text())
    assert "live pull failed" in body and "using stored corpus" in body
    assert "event: done" in body and "event: error" not in body


def test_generate_stream_skips_pull_when_fresh(client, monkeypatch):
    """Ingested within the last 12 hours -> no re-crawl; cached stages
    replay. The seeded fixture's ingested_at is now, so no backdating."""
    from app import main as app_main

    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")

    def boom(*args, **kwargs):
        raise AssertionError("live pull must not run when data is fresh")

    monkeypatch.setattr(app_main.ingest, "run_ingest", boom)
    week = _week(client)
    with client.stream(
        "GET",
        f"/api/generate/stream?week_start={week}&model_key=deepseek-v4",
    ) as resp:
        body = "".join(resp.iter_text())
    assert "live pull" not in body
    assert '"status": "cached"' in body
    assert "event: done" in body


def test_generate_stream_error_event(client):
    week = _week(client)
    with client.stream(
        "GET",
        f"/api/generate/stream?week_start={week}&model_key=not-a-model",
    ) as resp:
        body = "".join(resp.iter_text())
    assert "event: error" in body and "unknown model" in body


def test_ingest_week_requires_voyage_key(client):
    resp = client.post("/api/ingest/week")
    assert resp.status_code == 400
    assert "VOYAGE_API_KEY" in resp.json()["detail"]


def test_embeddings_endpoint(client):
    d = client.get("/api/embeddings").json()
    assert len(d["points"]) > 0
    point = d["points"][0]
    assert {
        "id", "x", "y", "title", "snippet", "cluster",
        "week_start", "retrieved_count",
    } <= set(point)
    weeks = {w["week_start"] for w in client.get("/api/status").json()["weeks"]}
    assert all(p["week_start"] in weeks for p in d["points"])
    assert d["method"] in ("pca", "umap")
    k = len(d["clusters"])
    assert k >= 2 and all(c["label"] for c in d["clusters"])
    assert all(0 <= p["cluster"] < k for p in d["points"])


def test_stats_endpoint_accumulates(client):
    before = client.get("/api/stats").json()
    _generate(client)
    after = client.get("/api/stats").json()
    assert after["total_retrievals"] > before["total_retrievals"]
    assert after["chunks_total"] == before["chunks_total"]
    assert after["top_chunks"][0]["retrieved_count"] >= 1


def test_bump_accounting_across_weeks(client, stub_llm):
    """Every retrieved chunk is counted exactly once in retrieval_stats."""
    weeks = sorted(w["week_start"] for w in client.get("/api/status").json()["weeks"])
    assert len(weeks) >= 2
    for week in weeks:
        assert _generate(client, week_start=week).status_code == 200

    docs = client.get("/api/documents?limit=100").json()
    expected = sum(len(d["retrieved_chunk_ids"]) for d in docs if d["mode"] == "rag")
    assert client.get("/api/stats").json()["total_retrievals"] == expected


def test_spa_served_at_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<div id=\"root\">" in resp.text

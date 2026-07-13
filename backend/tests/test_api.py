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
    assert set(d["models"]) == {"deepseek-v4"}
    assert d["models_available"] == []  # keyless
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
    # cached ingest stages first, then live retrieve/write
    assert stages[:3] == ["crawl", "reduce", "embed"]
    assert "retrieve" in stages and "write" in stages
    assert "event: done" in body
    done = json.loads(body.split("event: done\ndata: ")[1].split("\n")[0])
    assert done["week_start"] == week
    assert done["content_md"].startswith("# Community Voices")
    assert client.get(f"/api/documents/{done['id']}").status_code == 200


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

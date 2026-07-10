"""Unit tests: generation layer (retrieval fan-out, prompts, persistence)."""
import json

import pytest

from app import db, generate

from tests.conftest import STUB_DOC


def test_retrieve_context_dedupes_caps_and_bumps(seeded):
    conn, _, retriever, weeks = seeded
    chunks, meta = generate.retrieve_context(conn, retriever, weeks[0])
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))  # deduped across facet queries
    assert len(ids) <= generate.MAX_CONTEXT_CHUNKS
    assert meta["mode"] == "hybrid"
    counted = conn.execute(
        "SELECT COUNT(*), SUM(retrieved_count) FROM retrieval_stats"
    ).fetchone()
    assert counted[0] == len(ids) and counted[1] == len(ids)
    # every chunk belongs to the requested week
    allowed = generate.week_paths(conn, weeks[0])
    assert all(c.path in allowed for c in chunks)


def test_context_block_headers(seeded):
    conn, _, retriever, weeks = seeded
    chunks, _ = generate.retrieve_context(conn, retriever, weeks[0])
    block = generate._context_block(conn, chunks)
    assert 'title="' in block and "score=" in block and "comments=" in block


def test_generate_document_persists_row(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    doc_id = generate.generate_document(
        conn, retriever, week_start=weeks[0], mode="rag", model_key="deepseek-v4"
    )
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert row["mode"] == "rag"
    assert row["model_key"] == "deepseek-v4"
    assert row["retrieval_mode"] == "hybrid"
    assert row["latency_ms"] == 42
    assert row["input_tokens"] == 1000 and row["output_tokens"] == 500
    assert len(json.loads(row["retrieved_chunk_ids"])) > 0
    assert "## Predictions for next week" in row["content_md"]


def test_baseline_has_no_context_and_no_chunks(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    doc_id = generate.generate_document(
        conn, retriever, week_start=weeks[0], mode="baseline", model_key="deepseek-v4"
    )
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert row["retrieved_chunk_ids"] is None and row["retrieval_mode"] is None
    assert "<context>" not in stub_llm["complete"][-1]["user"]
    assert "NO access" in stub_llm["complete"][-1]["user"]


def test_prediction_review_uses_adjacent_prior_week(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    older, newer = weeks[1], weeks[0]  # weeks is newest-first
    generate.generate_document(
        conn, retriever, week_start=older, mode="rag", model_key="deepseek-v4"
    )
    generate.generate_document(
        conn, retriever, week_start=newer, mode="rag", model_key="deepseek-v4"
    )
    system = stub_llm["complete"][-1]["system"]
    assert "how did they hold up" in system
    assert "Prediction alpha" in system  # prior week's predictions embedded


def test_no_review_without_prior_week(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    generate.generate_document(
        conn, retriever, week_start=weeks[0], mode="rag", model_key="deepseek-v4"
    )
    assert "how did they hold up" not in stub_llm["complete"][-1]["system"]


def test_previous_predictions_extracts_section(seeded):
    conn, _, _, weeks = seeded
    older, newer = weeks[1], weeks[0]
    with conn:
        conn.execute(
            "INSERT INTO documents (mode, model_key, week_start, subreddit, content_md) "
            "VALUES ('rag', 'm', ?, 'test-community', ?)",
            (older, STUB_DOC.format(week=older, title="t")),
        )
    community = db.get_meta(conn, "subreddit")
    section = generate._previous_predictions(conn, community, newer)
    assert section.startswith("## Predictions for next week")
    assert "Prediction alpha" in section


def test_empty_week_raises(seeded, stub_llm):
    conn, _, retriever, _ = seeded
    with pytest.raises(ValueError, match="no chunks retrieved"):
        generate.generate_document(
            conn, retriever, week_start="1999-01-01", mode="rag",
            model_key="deepseek-v4",
        )


def test_comparisons_all_kinds(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    for kind, kwargs, expect_extra in [
        ("rag_vs_baseline", {}, False),
        ("model_vs_model", {"model_b": "deepseek-v4-flash"}, False),
        ("retrieval_vs_retrieval", {"retrieval_a": "hybrid", "retrieval_b": "bm25"}, True),
    ]:
        cid = generate.run_comparison(
            conn, retriever, kind=kind, week_start=weeks[0],
            model_a="deepseek-v4", **kwargs,
        )
        row = conn.execute("SELECT * FROM comparisons WHERE id = ?", (cid,)).fetchone()
        judge = json.loads(row["judge_json"])
        assert judge["winner"] in ("a", "b", "tie")
        if expect_extra:
            extra = json.loads(row["extra_json"])
            assert 0.0 <= extra["chunk_overlap_jaccard"] <= 1.0
        else:
            assert row["extra_json"] is None
    with pytest.raises(ValueError):
        generate.run_comparison(
            conn, retriever, kind="nope", week_start=weeks[0], model_a="deepseek-v4"
        )


def test_rag_vs_baseline_sides(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    cid = generate.run_comparison(
        conn, retriever, kind="rag_vs_baseline", week_start=weeks[0],
        model_a="deepseek-v4",
    )
    row = conn.execute("SELECT * FROM comparisons WHERE id = ?", (cid,)).fetchone()
    side_a = conn.execute(
        "SELECT mode FROM documents WHERE id = ?", (row["doc_a_id"],)
    ).fetchone()["mode"]
    side_b = conn.execute(
        "SELECT mode FROM documents WHERE id = ?", (row["doc_b_id"],)
    ).fetchone()["mode"]
    assert (side_a, side_b) == ("baseline", "rag")

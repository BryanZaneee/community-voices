"""Unit tests: generation layer (retrieval fan-out, prompts, persistence)."""
import json

import pytest

from app import generate


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


def test_report_json_stored_and_markdown_built(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    doc_id = generate.generate_document(
        conn, retriever, week_start=weeks[0], mode="rag", model_key="deepseek-v4"
    )
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    report = json.loads(row["report_json"])
    assert report["headline"] and len(report["topics"]) >= 3
    md = row["content_md"]
    assert md.startswith("# Community Voices")
    assert "### Studio layoffs" in md
    assert "_40% of discussion · 12 threads_" in md
    assert "_30% of discussion_" in md  # null threads omitted from the meta line
    assert "% confidence" in md


def test_bad_json_falls_back_to_raw_text(seeded, monkeypatch):
    from app import llm

    def broken_complete(model_key, system, user, json_schema=None):
        return llm.GenResult(
            text="not json at all", model_key=model_key,
            input_tokens=1, output_tokens=1, latency_ms=1,
        )

    monkeypatch.setattr(llm, "complete", broken_complete)
    conn, _, retriever, weeks = seeded
    doc_id = generate.generate_document(
        conn, retriever, week_start=weeks[0], mode="rag", model_key="deepseek-v4"
    )
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert row["content_md"] == "not json at all"
    assert row["report_json"] is None


def test_baseline_has_no_context_and_no_chunks(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    doc_id = generate.generate_document(
        conn, retriever, week_start=weeks[0], mode="baseline", model_key="deepseek-v4"
    )
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert row["retrieved_chunk_ids"] is None and row["retrieval_mode"] is None
    assert "<context>" not in stub_llm["complete"][-1]["user"]
    assert "NO access" in stub_llm["complete"][-1]["user"]


def test_empty_week_raises(seeded, stub_llm):
    conn, _, retriever, _ = seeded
    with pytest.raises(ValueError, match="no chunks retrieved"):
        generate.generate_document(
            conn, retriever, week_start="1999-01-01", mode="rag",
            model_key="deepseek-v4",
        )


def test_rag_vs_baseline_sides(seeded, stub_llm):
    conn, _, retriever, weeks = seeded
    cid = generate.run_comparison(
        conn, retriever, week_start=weeks[0], model_key="deepseek-v4"
    )
    row = conn.execute("SELECT * FROM comparisons WHERE id = ?", (cid,)).fetchone()
    judge = json.loads(row["judge_json"])
    assert judge["winner"] in ("a", "b", "tie")
    assert row["kind"] == "rag_vs_baseline" and row["extra_json"] is None
    side_a = conn.execute(
        "SELECT mode FROM documents WHERE id = ?", (row["doc_a_id"],)
    ).fetchone()["mode"]
    side_b = conn.execute(
        "SELECT mode FROM documents WHERE id = ?", (row["doc_b_id"],)
    ).fetchone()["mode"]
    assert (side_a, side_b) == ("baseline", "rag")

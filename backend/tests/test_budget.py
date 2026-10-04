"""Unit tests: budget.py — daily call caps persisted in meta, date rollover."""
import pytest

from app import budget, config, db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_REQUEST_COST_BOUNDS", '{"llm":1000,"embed":1000}')
    c = db.connect(tmp_path / "budget.sqlite")
    yield c
    c.close()


def test_charge_hits_cap_then_raises(conn, monkeypatch):
    monkeypatch.setattr(config, "DAILY_LLM_CALL_CAP", 2)
    budget.charge(conn, "llm")
    budget.charge(conn, "llm")
    with pytest.raises(budget.BudgetExhausted):
        budget.charge(conn, "llm")
    assert budget.usage(conn)["llm_used"] == 2  # the failed charge didn't count


@pytest.mark.parametrize("cap", [0, -1])
def test_nonpositive_cap_disables_paid_work(conn, monkeypatch, cap):
    monkeypatch.setattr(config, "DAILY_LLM_CALL_CAP", cap)
    with pytest.raises(budget.BudgetExhausted):
        budget.charge(conn, "llm")
    assert budget.usage(conn)["llm_used"] == 0


def test_date_rollover_resets_counter(conn, monkeypatch):
    monkeypatch.setattr(config, "DAILY_EMBED_CALL_CAP", 1)
    monkeypatch.setattr(budget, "_today", lambda: "2026-09-16")
    budget.charge(conn, "embed")
    with pytest.raises(budget.BudgetExhausted):
        budget.charge(conn, "embed")

    monkeypatch.setattr(budget, "_today", lambda: "2026-09-17")
    budget.charge(conn, "embed")  # new UTC day, fresh quota
    assert budget.usage(conn)["embed_used"] == 1


def test_kinds_have_independent_counters(conn, monkeypatch):
    monkeypatch.setattr(config, "DAILY_LLM_CALL_CAP", 1)
    monkeypatch.setattr(config, "DAILY_EMBED_CALL_CAP", 1)
    budget.charge(conn, "llm")
    budget.charge(conn, "embed")  # independent cap, must not raise
    usage = budget.usage(conn)
    assert usage == {"llm_used": 1, "llm_cap": 1, "embed_used": 1, "embed_cap": 1}


def test_bind_lets_call_sites_omit_conn(conn, monkeypatch):
    monkeypatch.setattr(config, "DAILY_LLM_CALL_CAP", 1)
    budget.bind(conn)
    try:
        budget.charge(None, "llm")
        with pytest.raises(budget.BudgetExhausted):
            budget.charge(None, "llm")
    finally:
        budget.bind(None)  # ponytail: don't leak this conn into other tests


@pytest.mark.parametrize("state", ["missing", "closed", "corrupt"])
def test_tracking_failure_denies_work(conn, monkeypatch, state):
    monkeypatch.setattr(budget, "_conn", None)
    if state == "closed":
        conn.close()
    elif state == "corrupt":
        db.set_meta(conn, f"budget:llm:{budget._today()}", "broken")
    with pytest.raises(budget.BudgetExhausted):
        budget.charge(None if state == "missing" else conn, "llm")


def test_independent_connections_cannot_overrun_cap(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("DEMO_REQUEST_COST_BOUNDS", '{"llm":1000}')
    monkeypatch.setattr(config, "DAILY_LLM_CALL_CAP", 3)
    path = tmp_path / "concurrent.sqlite"
    db.connect(path).close()

    def attempt(_):
        connection = db.connect(path)
        try:
            budget.charge(connection, "llm")
            return 1
        except budget.BudgetExhausted:
            return 0
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 3
    reopened = db.connect(path)
    try:
        assert budget.usage(reopened)["llm_used"] == 3
    finally:
        reopened.close()


def test_dollar_budget_is_shared_across_kinds(conn, monkeypatch):
    monkeypatch.setenv("DEMO_REQUEST_COST_BOUNDS", '{"llm":300000,"embed":300000}')
    budget.charge(conn, "llm")
    with pytest.raises(budget.BudgetExhausted, match="spending budget"):
        budget.charge(conn, "embed")
    assert budget.usage(conn)["embed_used"] == 0


def test_unconfigured_cost_blocks_work(conn, monkeypatch):
    monkeypatch.delenv("DEMO_REQUEST_COST_BOUNDS", raising=False)
    with pytest.raises(budget.BudgetExhausted, match="spending bound"):
        budget.charge(conn, "llm")

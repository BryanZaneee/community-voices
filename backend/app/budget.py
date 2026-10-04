"""Daily call-cap guards for the paid LLM and embedding API surfaces.

Counters persist in the `meta` table (keyed `budget:<kind>:<YYYY-MM-DD UTC>`)
so caps survive restarts. llm.py and rag/embeddings.py don't take a request
-scoped connection today, so callers charge against a connection bound once
at app startup (see main.py's lifespan) rather than threading one through
every call site.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Literal

from app import config, db

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


class BudgetExhausted(RuntimeError):
    """Raised when a charge would push a kind's daily count past its cap."""


def bind(conn: sqlite3.Connection | None) -> None:
    """Wire the shared lifespan connection so complete()/judge_json()/
    _embed() can charge without a conn argument at their call sites."""
    global _conn
    _conn = conn


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cap(kind: Literal["llm", "embed"]) -> int:
    return config.DAILY_LLM_CALL_CAP if kind == "llm" else config.DAILY_EMBED_CALL_CAP


def charge(conn: sqlite3.Connection | None, kind: Literal["llm", "embed"], operation: str | None = None) -> None:
    """Reserve a call durably before provider work; unavailable tracking denies it."""
    try:
        bounds = json.loads(os.environ.get("DEMO_REQUEST_COST_BOUNDS", "{}"))
        cost = bounds.get(operation or kind)
        if type(cost) is not int or not 0 < cost <= 500000:
            raise ValueError("missing cost bound")
    except (ValueError, TypeError, AttributeError) as exc:
        raise BudgetExhausted("paid generation paused: spending bound is not configured") from exc
    cap = _cap(kind)
    if cap <= 0:
        raise BudgetExhausted("paid generation is disabled")
    conn = conn or _conn
    if conn is None:
        raise BudgetExhausted("budget tracking unavailable")
    key = f"budget:{kind}:{_today()}"
    with _lock:
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                money_key = f"budget:microdollars:{_today()}"
                spent = int(db.get_meta(conn, money_key) or 0)
                if spent < 0 or spent + cost > 500000:
                    raise BudgetExhausted("daily demo spending budget exhausted")
                used = int(db.get_meta(conn, key) or 0)
                if used < 0:
                    raise ValueError("negative budget counter")
                if used >= cap:
                    raise BudgetExhausted(
                        "daily generation budget reached; resets at 00:00 UTC"
                    )
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(used + 1)),
                )
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (money_key, str(spent + cost)),
                )
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise BudgetExhausted("budget tracking unavailable") from exc


def usage(conn: sqlite3.Connection | None = None) -> dict:
    """Current day's used/cap counts for /api/status."""
    conn = conn or _conn
    today = _today()
    try:
        llm_used = int(db.get_meta(conn, f"budget:llm:{today}") or 0) if conn else 0
        embed_used = int(db.get_meta(conn, f"budget:embed:{today}") or 0) if conn else 0
    except sqlite3.ProgrammingError:
        llm_used = embed_used = 0
    return {
        "llm_used": llm_used,
        "llm_cap": config.DAILY_LLM_CALL_CAP,
        "embed_used": embed_used,
        "embed_cap": config.DAILY_EMBED_CALL_CAP,
    }

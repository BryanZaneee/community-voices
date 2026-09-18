"""Daily call-cap guards for the paid LLM and embedding API surfaces.

Counters persist in the `meta` table (keyed `budget:<kind>:<YYYY-MM-DD UTC>`)
so caps survive restarts. llm.py and rag/embeddings.py don't take a request
-scoped connection today, so callers charge against a connection bound once
at app startup (see main.py's lifespan) rather than threading one through
every call site.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Literal

from app import config, db

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


class BudgetExhausted(RuntimeError):
    """Raised when a charge would push a kind's daily count past its cap."""


def bind(conn: sqlite3.Connection) -> None:
    """Wire the shared lifespan connection so complete()/judge_json()/
    _embed() can charge without a conn argument at their call sites."""
    global _conn
    _conn = conn


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cap(kind: Literal["llm", "embed"]) -> int:
    return config.DAILY_LLM_CALL_CAP if kind == "llm" else config.DAILY_EMBED_CALL_CAP


def charge(conn: sqlite3.Connection | None, kind: Literal["llm", "embed"]) -> None:
    """Increment today's counter for `kind`; raise BudgetExhausted instead of
    incrementing if that would exceed the cap. A cap of 0 disables the check.
    `conn` defaults to the connection passed to bind()."""
    cap = _cap(kind)
    if cap <= 0:
        return
    conn = conn or _conn
    if conn is None:
        return  # ponytail: not bound yet (e.g. import-time use) — skip
    key = f"budget:{kind}:{_today()}"
    with _lock:
        try:
            used = int(db.get_meta(conn, key) or 0)
            if used >= cap:
                raise BudgetExhausted(
                    "daily generation budget reached; resets at 00:00 UTC"
                )
            db.set_meta(conn, key, str(used + 1))
        except sqlite3.ProgrammingError:
            return  # ponytail: bound conn closed (e.g. a prior test's lifespan)


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

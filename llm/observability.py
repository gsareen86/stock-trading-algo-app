"""
LLM call observability — persistent log of every LLM request.

Records to the llm_call_log table in the main DB. Every call through
llm/client.py writes one row regardless of outcome (success, failure,
cache hit). The dashboard reads from this table to show usage stats,
daily budget consumption, and per-feature breakdowns.

Schema
------
id              INTEGER PRIMARY KEY
ts              TEXT     ISO timestamp (UTC)
provider        TEXT     "anthropic" | "openrouter"
model           TEXT     full model id
caller          TEXT     feature name: sentiment|veto|regime|events|eod_review|meta_weights
status          TEXT     "ok" | "cached" | "rate_limited" | "circuit_open" | "error"
prompt_tokens   INTEGER  input tokens (None if unavailable)
completion_tokens INTEGER output tokens (None if unavailable)
total_tokens    INTEGER  sum (None if unavailable)
latency_ms      INTEGER  wall-clock ms for the API call (0 for cache hits)
error_msg       TEXT     first 200 chars of error message on failure
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


_INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS ix_llm_call_log_ts     ON llm_call_log(ts)",
    "CREATE INDEX IF NOT EXISTS ix_llm_call_log_caller ON llm_call_log(caller)",
]

_initialized = False

# Backend-aware DDL: SQLite uses INTEGER PRIMARY KEY (implicit rowid autoincrement);
# PostgreSQL requires SERIAL so the id column gets a sequence and auto-fills.
_TABLE_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS llm_call_log (
    id                INTEGER PRIMARY KEY,
    ts                TEXT    NOT NULL,
    provider          TEXT    NOT NULL,
    model             TEXT    NOT NULL,
    caller            TEXT    NOT NULL DEFAULT '',
    status            TEXT    NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    latency_ms        INTEGER,
    error_msg         TEXT
)
"""

_TABLE_DDL_PG = """
CREATE TABLE IF NOT EXISTS llm_call_log (
    id                SERIAL  PRIMARY KEY,
    ts                TEXT    NOT NULL,
    provider          TEXT    NOT NULL,
    model             TEXT    NOT NULL,
    caller            TEXT    NOT NULL DEFAULT '',
    status            TEXT    NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    latency_ms        INTEGER,
    error_msg         TEXT
)
"""


def _ensure_table() -> None:
    global _initialized
    if _initialized:
        return
    try:
        from db.models import get_conn, BACKEND
        ddl = _TABLE_DDL_PG if BACKEND == "postgres" else _TABLE_DDL_SQLITE
        with get_conn() as conn:
            conn.execute(ddl)
            for idx in _INDEXES_DDL:
                conn.execute(idx)
        _initialized = True
    except Exception as e:
        log.warning("llm_call_log table init failed (non-fatal): %s", e)


def record(
    *,
    provider: str,
    model: str,
    caller: str,
    status: str,                        # "ok" | "cached" | "rate_limited" | "error"
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    error_msg: Optional[str] = None,
) -> None:
    """Write one row to llm_call_log. Silent on any DB error."""
    _ensure_table()
    total = (
        (prompt_tokens or 0) + (completion_tokens or 0)
        if (prompt_tokens is not None or completion_tokens is not None)
        else None
    )
    try:
        from db.models import get_conn
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO llm_call_log
                   (ts, provider, model, caller, status,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, error_msg)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    provider, model, caller, status,
                    prompt_tokens, completion_tokens, total,
                    latency_ms,
                    (error_msg or "")[:200] or None,
                ),
            )
    except Exception as e:
        log.debug("llm_call_log write failed (non-fatal): %s", e)


# ── Query helpers used by the dashboard ──────────────────────────────

def daily_summary(days: int = 7) -> list[dict]:
    """Rows: {date, calls, ok, cached, errors, prompt_tokens, completion_tokens}."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT
                       substr(ts,1,10)            AS date,
                       COUNT(*)                   AS calls,
                       SUM(status='ok')            AS ok,
                       SUM(status='cached')        AS cached,
                       SUM(status IN ('error','rate_limited','circuit_open')) AS errors,
                       COALESCE(SUM(prompt_tokens),0)     AS prompt_tokens,
                       COALESCE(SUM(completion_tokens),0) AS completion_tokens
                   FROM llm_call_log
                   WHERE ts >= datetime('now',?)
                   GROUP BY date
                   ORDER BY date DESC""",
                (f"-{days} days",),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def today_by_caller() -> list[dict]:
    """Rows: {caller, calls, ok, cached, errors, total_tokens} for today."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT
                       caller,
                       COUNT(*)                   AS calls,
                       SUM(status='ok')            AS ok,
                       SUM(status='cached')        AS cached,
                       SUM(status IN ('error','rate_limited','circuit_open')) AS errors,
                       COALESCE(SUM(total_tokens),0) AS total_tokens,
                       COALESCE(AVG(CASE WHEN status='ok' THEN latency_ms END),0) AS avg_latency_ms
                   FROM llm_call_log
                   WHERE substr(ts,1,10) = date('now')
                   GROUP BY caller
                   ORDER BY calls DESC""",
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def recent_calls(limit: int = 100) -> list[dict]:
    """Most recent N calls for the live log view."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT ts, provider, model, caller, status,
                          prompt_tokens, completion_tokens, total_tokens,
                          latency_ms, error_msg
                   FROM llm_call_log
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def today_totals() -> dict:
    """Quick summary dict for the sidebar / header badges."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                """SELECT
                       COUNT(*)                              AS calls,
                       SUM(status='ok')                      AS ok,
                       SUM(status='cached')                  AS cached,
                       SUM(status IN ('error','rate_limited','circuit_open')) AS errors,
                       COALESCE(SUM(total_tokens),0)         AS tokens
                   FROM llm_call_log
                   WHERE substr(ts,1,10) = date('now')""",
            ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}

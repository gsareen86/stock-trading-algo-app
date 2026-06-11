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

_TABLE_DDL = """
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

_INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS ix_llm_call_log_ts     ON llm_call_log(ts)",
    "CREATE INDEX IF NOT EXISTS ix_llm_call_log_caller ON llm_call_log(caller)",
]

_initialized = False


def _ensure_table() -> None:
    global _initialized
    if _initialized:
        return
    try:
        from db.models import get_conn
        with get_conn() as conn:
            conn.execute(_TABLE_DDL)
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
# NOTE: cutoffs are computed in Python and the boolean sums use portable
# CASE WHEN so every query works identically on SQLite and Postgres.
# (The previous SQLite-only forms — date('now'), SUM(status='ok') — threw
# on Postgres, were swallowed by the except, and the dashboard showed
# nothing.)

_OK_SUM     = "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END)"
_CACHED_SUM = "SUM(CASE WHEN status='cached' THEN 1 ELSE 0 END)"
_ERR_SUM    = ("SUM(CASE WHEN status IN ('error','rate_limited','circuit_open')"
               " THEN 1 ELSE 0 END)")


def _utc_cutoff_days(days: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _today_cutoff_utc_iso() -> str:
    """Start of "today" in IST, expressed as a UTC ISO timestamp.

    Rows are logged with UTC timestamps; the user lives in IST. Comparing
    on the UTC *date* made every call between 00:00-05:30 IST (and any call
    logged the previous UTC day) vanish from "today" — the dashboard showed
    zeros all evening. Compare against the IST midnight instant instead.
    """
    from datetime import timedelta
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    ist_midnight_utc = (ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
                        - timedelta(hours=5, minutes=30))
    return ist_midnight_utc.isoformat()


# ── Cost estimation ──────────────────────────────────────────────────

def pricing_for(provider: str, model: str):
    """(input_usd_per_mtok, output_usd_per_mtok) or None when unknown.
    Local providers are free; unknown models return None so the UI can say
    "add pricing in config.py" instead of showing a silently wrong number."""
    try:
        from config import LLM_PRICING_USD_PER_MTOK as table
    except ImportError:
        return None
    provider = (provider or "").lower()
    model = (model or "").lower()
    exact = table.get(f"{provider}:{model}")
    if exact is not None:
        return exact
    best, best_len = None, -1
    for pattern, price in table.items():
        if ":" in pattern and not pattern.startswith(":"):
            continue  # provider-scoped patterns handled below
        if pattern and pattern in model and len(pattern) > best_len:
            best, best_len = price, len(pattern)
    if best is not None:
        return best
    return table.get(f"{provider}:*")


def estimate_cost_usd(provider: str, model: str,
                      prompt_tokens, completion_tokens):
    """Estimated USD cost of one call, or None when pricing is unknown."""
    price = pricing_for(provider, model)
    if price is None:
        return None
    pt = float(prompt_tokens or 0)
    ct = float(completion_tokens or 0)
    return (pt * price[0] + ct * price[1]) / 1_000_000.0


def daily_summary(days: int = 7) -> list[dict]:
    """Rows: {date, calls, ok, cached, errors, prompt_tokens, completion_tokens}."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT
                       substr(ts,1,10)            AS date,
                       COUNT(*)                   AS calls,
                       {_OK_SUM}                  AS ok,
                       {_CACHED_SUM}              AS cached,
                       {_ERR_SUM}                 AS errors,
                       COALESCE(SUM(prompt_tokens),0)     AS prompt_tokens,
                       COALESCE(SUM(completion_tokens),0) AS completion_tokens
                   FROM llm_call_log
                   WHERE ts >= ?
                   GROUP BY substr(ts,1,10)
                   ORDER BY date DESC""",
                (_utc_cutoff_days(days),),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def today_by_caller() -> list[dict]:
    """Rows: {caller, calls, ok, cached, errors, total_tokens} for today (UTC)."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT
                       caller,
                       COUNT(*)                   AS calls,
                       {_OK_SUM}                  AS ok,
                       {_CACHED_SUM}              AS cached,
                       {_ERR_SUM}                 AS errors,
                       COALESCE(SUM(total_tokens),0) AS total_tokens,
                       COALESCE(AVG(CASE WHEN status='ok' THEN latency_ms END),0) AS avg_latency_ms
                   FROM llm_call_log
                   WHERE ts >= ?
                   GROUP BY caller
                   ORDER BY calls DESC""",
                (_today_cutoff_utc_iso(),),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def by_model(days: int = 7) -> list[dict]:
    """Provider/model usage breakdown over the last N days.

    Rows: {provider, model, calls, ok, cached, errors,
           prompt_tokens, completion_tokens, total_tokens,
           avg_latency_ms, last_used}.
    Lets the dashboard show exactly which models burned which tokens
    (e.g. "anthropic / claude-sonnet-4-6" vs "ollama / gemma3:9b").
    """
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT
                       provider,
                       model,
                       COUNT(*)                   AS calls,
                       {_OK_SUM}                  AS ok,
                       {_CACHED_SUM}              AS cached,
                       {_ERR_SUM}                 AS errors,
                       COALESCE(SUM(prompt_tokens),0)     AS prompt_tokens,
                       COALESCE(SUM(completion_tokens),0) AS completion_tokens,
                       COALESCE(SUM(total_tokens),0)      AS total_tokens,
                       COALESCE(AVG(CASE WHEN status='ok' THEN latency_ms END),0) AS avg_latency_ms,
                       MAX(ts)                    AS last_used
                   FROM llm_call_log
                   WHERE ts >= ?
                   GROUP BY provider, model
                   ORDER BY total_tokens DESC, calls DESC""",
                (_utc_cutoff_days(days),),
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
                """SELECT id, ts, provider, model, caller, status,
                          prompt_tokens, completion_tokens, total_tokens,
                          latency_ms, error_msg
                   FROM llm_call_log
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def alltime_totals() -> dict:
    """All-time calls/tokens + estimated USD cost (sums per provider+model
    so each row prices under its own rate)."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT provider, model,
                          COUNT(*) AS calls,
                          COALESCE(SUM(prompt_tokens),0)     AS pt,
                          COALESCE(SUM(completion_tokens),0) AS ct
                   FROM llm_call_log GROUP BY provider, model"""
            ).fetchall()
        calls = tokens = 0
        cost = 0.0
        unknown = False
        for r in rows:
            calls += int(r["calls"] or 0)
            tokens += int(r["pt"] or 0) + int(r["ct"] or 0)
            c = estimate_cost_usd(r["provider"], r["model"], r["pt"], r["ct"])
            if c is None:
                unknown = True
            else:
                cost += c
        return {"calls": calls, "tokens": tokens,
                "est_cost_usd": round(cost, 4), "pricing_incomplete": unknown}
    except Exception:
        return {"calls": 0, "tokens": 0, "est_cost_usd": 0.0, "pricing_incomplete": False}


def today_cost_usd() -> tuple:
    """(est_cost_usd, pricing_incomplete) for today (IST)."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT provider, model,
                          COALESCE(SUM(prompt_tokens),0)     AS pt,
                          COALESCE(SUM(completion_tokens),0) AS ct
                   FROM llm_call_log WHERE ts >= ?
                   GROUP BY provider, model""",
                (_today_cutoff_utc_iso(),),
            ).fetchall()
        cost, unknown = 0.0, False
        for r in rows:
            c = estimate_cost_usd(r["provider"], r["model"], r["pt"], r["ct"])
            if c is None:
                unknown = True
            else:
                cost += c
        return round(cost, 4), unknown
    except Exception:
        return 0.0, False


def today_totals() -> dict:
    """Quick summary dict for the sidebar / header badges (today, UTC)."""
    _ensure_table()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                f"""SELECT
                       COUNT(*)                              AS calls,
                       {_OK_SUM}                             AS ok,
                       {_CACHED_SUM}                         AS cached,
                       {_ERR_SUM}                            AS errors,
                       COALESCE(SUM(prompt_tokens),0)        AS prompt_tokens,
                       COALESCE(SUM(completion_tokens),0)    AS completion_tokens,
                       COALESCE(SUM(total_tokens),0)         AS tokens
                   FROM llm_call_log
                   WHERE ts >= ?""",
                (_today_cutoff_utc_iso(),),
            ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}

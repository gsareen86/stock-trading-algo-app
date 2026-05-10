"""
End-of-day post-trade review.

Runs once per trading day around 16:00 IST. Pulls the day's closed trades
plus the strategy weights and threshold settings that were active, sends
the bundle to Claude (Opus by default — pattern recognition matters here),
and gets back:

  1. Loss-pattern analysis  (what went wrong, why)
  2. Win-pattern analysis   (what worked)
  3. Concrete parameter recommendations with old/new values

Recommendations are written to the database and surfaced in the dashboard
for the user to accept or reject one-by-one. We never auto-apply changes
to the bot's risk parameters — that's a human-in-the-loop decision.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from config import IST, LLM_EOD_MODEL, STRATEGY_WEIGHTS
from db.models import get_conn
from llm.client import call_json

log = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentence day summary"},
        "loss_patterns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete patterns observed in losing trades",
        },
        "win_patterns": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "param": {"type": "string"},
                    "current": {"type": "string"},
                    "suggested": {"type": "string"},
                    "reason": {"type": "string"},
                    "expected_impact": {"type": "string"},
                },
                "required": ["param", "current", "suggested", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "loss_patterns", "win_patterns", "recommendations"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are an Indian-equity intraday quant reviewing a day's trades for a "
    "systematic 15-min bot trading NIFTY 500. Your job: find PATTERNS in "
    "losers (not just list trades), and suggest concrete config changes. "
    "Configurable params include STRATEGY_WEIGHTS, MIN_COMPOSITE_SCORE, "
    "NO_TRADE_AFTER, NO_TRADE_WINDOWS, ATR_STOP_MULT, ATR_T1_MULT. "
    "Be specific: don't say 'tighten stops' — say 'ATR_STOP_MULT 1.5 → 1.2'. "
    "Limit recommendations to the 3 highest-impact changes."
)


def _fetch_today_trades() -> list[dict]:
    """Return today's closed trade rows."""
    today_start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today_start.isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT t.ts, t.ticker, t.side, t.quantity, t.price, t.value,
                      t.costs, t.net_value, t.strategy, t.composite_score, t.reason,
                      p.entry_price, p.stop_loss, p.take_profit, p.high_water_mark
               FROM trades t
               LEFT JOIN positions p ON p.id = t.position_id
               WHERE t.ts >= ? AND t.side IN ('SELL', 'COVER')
               ORDER BY t.ts""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def _format_trades(trades: list[dict]) -> str:
    if not trades:
        return "(no closed trades today)"
    lines = []
    for t in trades:
        entry = t.get("entry_price")
        exit_p = t.get("price")
        if entry and exit_p:
            pnl_pct = (exit_p - entry) / entry * 100
            if t.get("side") == "COVER":
                pnl_pct = -pnl_pct
        else:
            pnl_pct = 0.0
        lines.append(
            f"- {(t.get('ts') or '')[:16]} {t.get('ticker')} "
            f"{t.get('side')} qty={t.get('quantity')} "
            f"entry={entry} exit={exit_p} pnl={pnl_pct:+.2f}% "
            f"strategy={t.get('strategy')} score={t.get('composite_score')} "
            f"reason={(t.get('reason') or '')[:80]}"
        )
    return "\n".join(lines)


def run_eod_review() -> Optional[dict]:
    """Run the EOD analysis and persist it. Returns the review dict or None."""
    trades = _fetch_today_trades()
    if not trades:
        log.info("EOD review: no closed trades today, skipping")
        return None

    weights_str = ", ".join(f"{k}={v:.2f}" for k, v in STRATEGY_WEIGHTS.items())
    prompt = (
        f"Date: {datetime.now(IST).strftime('%Y-%m-%d')}\n"
        f"Active strategy weights: {weights_str}\n\n"
        f"Closed trades:\n{_format_trades(trades)}\n\n"
        "Output ONLY the JSON object."
    )

    review = call_json(
        prompt=prompt,
        schema=_SCHEMA,
        system=_SYSTEM,
        model=LLM_EOD_MODEL,
        max_tokens=1500,
        caller="eod_review",
    )
    if review is None:
        return None

    _persist_review(review)
    return review


def _persist_review(review: dict) -> None:
    today = date.today().isoformat()
    try:
        with get_conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS llm_eod_reviews (
                       id INTEGER PRIMARY KEY,
                       review_date TEXT NOT NULL UNIQUE,
                       created_at TEXT NOT NULL,
                       summary TEXT,
                       loss_patterns TEXT,
                       win_patterns TEXT,
                       recommendations TEXT,
                       status TEXT DEFAULT 'pending'
                   )"""
            )
            conn.execute(
                """INSERT OR REPLACE INTO llm_eod_reviews
                   (review_date, created_at, summary, loss_patterns,
                    win_patterns, recommendations, status)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    today,
                    datetime.now(IST).isoformat(),
                    review.get("summary", ""),
                    json.dumps(review.get("loss_patterns", [])),
                    json.dumps(review.get("win_patterns", [])),
                    json.dumps(review.get("recommendations", [])),
                    "pending",
                ),
            )
        log.info("EOD review persisted with %d recommendations",
                 len(review.get("recommendations", [])))
    except Exception as e:
        log.warning("EOD review DB write failed (non-fatal): %s", e)


def latest_review() -> Optional[dict]:
    """Read the most recent EOD review back from DB. For dashboard rendering."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT * FROM llm_eod_reviews
                   ORDER BY review_date DESC LIMIT 1"""
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("loss_patterns", "win_patterns", "recommendations"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except Exception:
                d[k] = []
        return d
    except Exception:
        return None

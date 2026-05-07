"""
Pre-trade LLM veto gate.

Runs after the composite scorer has already decided to enter a position. The
LLM gets the full context — signal action, score, regime, recent news — and
returns one of three verdicts:

  PROCEED  — take full position size
  REDUCE   — take 50% size (signal is plausible but marginal)
  SKIP     — don't trade (LLM identified a blocking risk)

This is the highest-leverage LLM feature for P&L because it acts as a final
filter on every trade. The biggest losses on this bot historically come from
correct-strategy / wrong-context situations:

  - Shorting a stock with a fresh positive announcement
  - Longing into a known earnings event
  - Mean-reversion shorts on a strong-trend day
  - Marginal composite scores (60-65) that are just noise

Claude sees the *narrative* the technical signals don't.

Designed to fail open: if the LLM call fails, returns PROCEED with the original
size. The bot's existing defences (regime filter, ATR stops) still apply.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from config import IST, LLM_VETO_MODEL
from llm.client import call_json

log = logging.getLogger(__name__)

VERDICT_PROCEED = "PROCEED"
VERDICT_REDUCE = "REDUCE"
VERDICT_SKIP = "SKIP"

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": [VERDICT_PROCEED, VERDICT_REDUCE, VERDICT_SKIP],
        },
        "reason": {
            "type": "string",
            "description": "≤ 25 words explaining the verdict",
        },
        "confidence": {"type": "number"},
    },
    "required": ["verdict", "reason", "confidence"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a strict Indian-equity intraday risk officer. Your job is to "
    "veto bad trades, not generate them. Default to PROCEED unless you spot a "
    "specific reason to be cautious. Hard rules:\n"
    "  • Never SHORT a stock with positive news in the last 2 hours.\n"
    "  • Never LONG a stock that has earnings in the next 1-2 trading days.\n"
    "  • SKIP marginal signals (composite < 65) unless news strongly supports them.\n"
    "  • REDUCE in high-VIX or counter-trend setups (regime conflicts with signal).\n"
    "  • SKIP mean-reversion shorts on a strongly trending day (regime=bullish + SELL).\n"
    "Confidence: 1.0 = certain, 0.5 = leaning, 0.0 = coin flip."
)


def llm_veto(
    *,
    ticker: str,
    side: str,                       # "LONG" or "SHORT"
    price: float,
    composite_score: float,
    technical_score: float,
    sentiment_score: float,          # -1..+1 raw
    fired_strategies: Iterable[tuple[str, str, float]],  # (name, action, score)
    regime: str,                     # "bullish" | "bearish" | "neutral"
    recent_news: Iterable[dict],     # [{title, ts, sentiment}]
    sector: str = "",
) -> tuple[str, str]:
    """Returns (verdict, reason). Fails open with (PROCEED, "llm unavailable")."""
    fired_summary = ", ".join(
        f"{n}:{a}({s:.0f})" for n, a, s in fired_strategies
    ) or "(none)"
    news_lines = []
    for n in list(recent_news)[:5]:
        ts = (n.get("ts") or "")[:16]
        sent = n.get("sentiment")
        sent_str = f" [{sent:+.2f}]" if isinstance(sent, (int, float)) else ""
        news_lines.append(f"- {ts}{sent_str} {n.get('title', '')[:120]}")
    news_block = "\n".join(news_lines) or "(no news in last 24h)"

    prompt = (
        f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}\n"
        f"NIFTY regime: {regime}\n\n"
        f"Trade: {side} {ticker} @ ₹{price:.2f}"
        f"{f' (sector: {sector})' if sector else ''}\n"
        f"Composite score: {composite_score:.0f} / 100\n"
        f"Technical score: {technical_score:.0f} / 100\n"
        f"Aggregated sentiment: {sentiment_score:+.2f}\n"
        f"Strategies firing: {fired_summary}\n\n"
        f"Recent news (last 24h):\n{news_block}\n\n"
        "Output ONLY the JSON object."
    )

    result = call_json(
        prompt=prompt,
        schema=_SCHEMA,
        system=_SYSTEM,
        model=LLM_VETO_MODEL,
        max_tokens=300,
    )
    if result is None:
        return VERDICT_PROCEED, "llm unavailable; fail open"

    verdict = result.get("verdict", VERDICT_PROCEED)
    reason = result.get("reason", "")
    if verdict not in (VERDICT_PROCEED, VERDICT_REDUCE, VERDICT_SKIP):
        return VERDICT_PROCEED, f"unrecognised verdict {verdict!r}; fail open"
    return verdict, reason


def apply_veto_to_qty(qty: int, verdict: str) -> int:
    """Translate verdict → final quantity. SKIP → 0; REDUCE → 50%; PROCEED → unchanged."""
    if verdict == VERDICT_SKIP:
        return 0
    if verdict == VERDICT_REDUCE:
        return max(1, qty // 2) if qty > 0 else 0
    return qty

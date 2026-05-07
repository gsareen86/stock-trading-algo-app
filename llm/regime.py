"""
LLM-based market regime classification.

Augments the existing technical regime filter (NIFTY price vs 20-EMA) with
narrative awareness. The technical filter only sees price; it can't tell:

  - It's RBI policy day (high vol, fade extremes)
  - Budget day or election result day (high vol, no new entries)
  - Q-results week for Nifty heavyweights (sector dispersion)
  - Global risk-off (Fed surprise, geopolitical event)

We feed Claude the technical regime + recent NIFTY headlines + India VIX,
and it returns one of four moods:

  BULLISH   → take longs only
  BEARISH   → take shorts only
  VOLATILE  → take both but reduce size 50%
  AVOID     → no new entries today

The runner uses this to *modulate* the existing regime, not replace it. If
Claude says AVOID and technical says bullish, no new entries get through.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from config import IST, LLM_REGIME_MODEL
from llm.client import call_json

log = logging.getLogger(__name__)

MOOD_BULLISH = "BULLISH"
MOOD_BEARISH = "BEARISH"
MOOD_VOLATILE = "VOLATILE"
MOOD_AVOID = "AVOID"

_SCHEMA = {
    "type": "object",
    "properties": {
        "mood": {
            "type": "string",
            "enum": [MOOD_BULLISH, MOOD_BEARISH, MOOD_VOLATILE, MOOD_AVOID],
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string", "description": "≤ 20 words"},
    },
    "required": ["mood", "confidence", "reason"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are an Indian-market intraday strategist classifying today's regime "
    "for a 15-min systematic trading bot. Inputs: NIFTY 50 technical trend, "
    "India VIX, top headlines. Output one of:\n"
    "  BULLISH  — strong uptrend / positive macro → longs only\n"
    "  BEARISH  — strong downtrend / risk-off → shorts only\n"
    "  VOLATILE — high VIX or event-day uncertainty → trade both sides at half size\n"
    "  AVOID    — major event today (RBI, Budget, election results, Fed) → no entries\n"
    "Be conservative on AVOID — only flag for confirmed near-term catalysts. "
    "Default: extend the technical regime unless you see narrative reasons to disagree."
)


def classify_regime(
    *,
    nifty_price: float,
    nifty_ema20: float,
    technical_regime: str,           # output of nifty_regime() — bullish/bearish/neutral
    vix: Optional[float] = None,
    headlines: Iterable[str] = (),
) -> tuple[str, str]:
    """Returns (mood, reason). Fails open with (BULLISH/NEUTRAL passthrough, "...").

    Called once per cycle. Cheap: ~150 tokens in, ~80 tokens out.
    """
    head_lines = [f"- {h[:160]}" for h in list(headlines)[:8]] or ["(no headlines)"]
    vix_str = f"{vix:.1f}" if isinstance(vix, (int, float)) else "n/a"

    prompt = (
        f"Date/time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}\n"
        f"NIFTY 50: {nifty_price:.0f} vs EMA20 {nifty_ema20:.0f} "
        f"({(nifty_price - nifty_ema20) / nifty_ema20 * 100:+.2f}%)\n"
        f"Technical regime: {technical_regime}\n"
        f"India VIX: {vix_str}\n"
        f"Top headlines:\n" + "\n".join(head_lines) + "\n\n"
        "Output ONLY the JSON object."
    )

    result = call_json(
        prompt=prompt,
        schema=_SCHEMA,
        system=_SYSTEM,
        model=LLM_REGIME_MODEL,
        max_tokens=200,
    )
    if result is None:
        # Fail open — map technical regime to mood
        fallback = {
            "bullish": MOOD_BULLISH,
            "bearish": MOOD_BEARISH,
            "neutral": MOOD_VOLATILE,
        }.get(technical_regime, MOOD_VOLATILE)
        return fallback, "llm unavailable; using technical regime"

    mood = result.get("mood", MOOD_VOLATILE)
    return mood, result.get("reason", "")


def mood_to_gates(mood: str) -> tuple[bool, bool, float]:
    """Translate LLM mood to (allow_long, allow_short, size_multiplier)."""
    if mood == MOOD_BULLISH:
        return True, False, 1.0
    if mood == MOOD_BEARISH:
        return False, True, 1.0
    if mood == MOOD_VOLATILE:
        return True, True, 0.5
    if mood == MOOD_AVOID:
        return False, False, 0.0
    return True, True, 1.0

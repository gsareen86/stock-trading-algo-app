"""
LLM-driven adaptive strategy weights.

Replaces the static STRATEGY_WEIGHTS dict with one Claude recomputes each
cycle based on current market conditions. The intuition:

  - On a strongly trending morning: vwap_momentum + orb + supertrend should
    dominate; vwap_reversion should sit on the bench.
  - On a flat low-VIX afternoon: vwap_reversion + pair_trading get the weight;
    breakout strategies are noise.
  - In high-VIX events: gap_play and supertrend (high-conviction) get more;
    everything else gets less.

The static weights stay as a baseline. We don't replace them — we compute a
delta and apply it. If the LLM call fails, the static dict is used unchanged.

Cached for 1 hour (4 cycles) — market conditions don't change minute-to-minute.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from config import IST, LLM_META_MODEL, STRATEGY_WEIGHTS
from llm.client import call_json

log = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "weights": {
            "type": "object",
            "additionalProperties": {"type": "number"},
            "description": "Strategy name → weight (must sum to ≈ 1.0)",
        },
        "reason": {"type": "string", "description": "≤ 30 words"},
    },
    "required": ["weights", "reason"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You re-balance intraday strategy weights for an Indian-equity bot based "
    "on live market conditions. Strategies available: ema_crossover, "
    "rsi_mean_reversion, bollinger_breakout, momentum, vwap_momentum, orb, "
    "vwap_reversion, supertrend, gap_play, pair_trading.\n\n"
    "Heuristics:\n"
    "  • Trending up + low VIX → up-weight vwap_momentum, orb, supertrend\n"
    "  • Trending down → up-weight supertrend, gap_play (short bias)\n"
    "  • Rangebound + low VIX → up-weight vwap_reversion, pair_trading, rsi_mean_reversion\n"
    "  • High VIX (>20) → up-weight high-conviction (gap_play, supertrend); cut mean-reversion\n"
    "  • Last hour (14:30+) → bias toward fast-exit strategies (orb, gap_play)\n\n"
    "Output weights summing to ~1.0. Don't deviate from baseline by more than ±0.10 per strategy "
    "(stability is more valuable than aggression). Round to 2 decimals."
)

# Hourly cache key — one call per hour is plenty
def _cache_key() -> str:
    now = datetime.now(IST)
    return f"meta_weights_{now.strftime('%Y%m%d_%H')}"


def adaptive_weights(
    *,
    technical_regime: str,            # bullish/bearish/neutral
    vix: Optional[float] = None,
    nifty_change_pct: Optional[float] = None,
) -> dict:
    """Return a strategy_name → weight dict. Always returns something usable —
    falls back to static STRATEGY_WEIGHTS if the LLM call fails.
    """
    baseline = ", ".join(f"{k}={v:.2f}" for k, v in STRATEGY_WEIGHTS.items())
    vix_str = f"{vix:.1f}" if isinstance(vix, (int, float)) else "n/a"
    chg_str = f"{nifty_change_pct:+.2f}%" if isinstance(nifty_change_pct, (int, float)) else "n/a"

    prompt = (
        f"Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}\n"
        f"Technical regime: {technical_regime}\n"
        f"NIFTY change today: {chg_str}\n"
        f"India VIX: {vix_str}\n"
        f"Baseline weights: {baseline}\n\n"
        "Output ONLY the JSON object."
    )

    result = call_json(
        prompt=prompt,
        schema=_SCHEMA,
        system=_SYSTEM,
        model=LLM_META_MODEL,
        max_tokens=400,
        cache_key=_cache_key(),
    )
    if result is None:
        return dict(STRATEGY_WEIGHTS)

    weights = result.get("weights", {})
    # Sanity-check + fill missing with baseline
    out = dict(STRATEGY_WEIGHTS)
    for k, v in weights.items():
        if k in out and isinstance(v, (int, float)) and 0 <= v <= 1:
            out[k] = float(v)

    # Clamp drift: no single weight should move more than ±0.15 from baseline
    for k in out:
        delta = out[k] - STRATEGY_WEIGHTS[k]
        if abs(delta) > 0.15:
            out[k] = STRATEGY_WEIGHTS[k] + (0.15 if delta > 0 else -0.15)

    # Renormalise to sum to 1.0
    total = sum(out.values())
    if total > 0:
        out = {k: v / total for k, v in out.items()}
    log.info("LLM meta-weights: %s", result.get("reason", ""))
    return out

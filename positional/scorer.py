"""
Positional Candidate Scorecard.

Turns the four positional strategies plus fundamental/market context into a
single coherent verdict per stock. Two ideas drive it:

1. Confluence — the strategies are *evidence*, not independent decisions. They
   vote into one technical pillar; more agreeing strategies → higher score.

2. Two-axis horizon — entry setups (all four strategies) answer "is there a
   trade NOW?" (Axis A = timing). The business behind the move answers "can it
   COMPOUND?" (Axis B = durability). Crossing the two axes yields the label:

        timing strong + durability strong  → BOTH
        timing strong + durability weak    → POSITIONAL
        timing weak   + durability strong  → LONG_TERM   (watch / accumulate)
        otherwise                          → AVOID

The composite blends five pillars (technical, quality, valuation, momentum,
sentiment). A sixth — management outlook — is added by the Phase-3 research
engine; until then the composite renormalises over the pillars present.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import (
    POSITIONAL_CONFLUENCE_BONUS,
    POSITIONAL_DURABILITY_STRONG,
    POSITIONAL_DURABILITY_WEIGHTS,
    POSITIONAL_MIN_TREND_SCORE,
    POSITIONAL_PILLAR_WEIGHTS,
    POSITIONAL_STRATEGY_WEIGHTS,
    POSITIONAL_TIMING_STRONG,
)
from positional.strategies.base import PositionalSignal

log = logging.getLogger(__name__)

# Horizon labels
HORIZON_BOTH = "BOTH"
HORIZON_POSITIONAL = "POSITIONAL"
HORIZON_LONG_TERM = "LONG_TERM"
HORIZON_AVOID = "AVOID"


@dataclass
class Scorecard:
    ticker: str
    price: float
    action: str                              # 'BUY' | 'WATCH' | 'HOLD'
    horizon: str                             # BOTH | POSITIONAL | LONG_TERM | AVOID
    conviction: str                          # 'high' | 'medium' | 'low'
    composite_score: float                   # 0-100 blended pillar composite
    timing_score: float                      # Axis A (= technical pillar)
    durability_score: float                  # Axis B (quality + valuation [+ mgmt])
    confluence: int                          # number of strategies firing BUY
    strategies_fired: List[str] = field(default_factory=list)
    est_hold_days: int = 15
    pillars: Dict[str, float] = field(default_factory=dict)
    signals: List[PositionalSignal] = field(default_factory=list)
    reason: str = ""


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ── Technical pillar: confluence of the four strategies ─────────────────────

def technical_pillar(signals: List[PositionalSignal]) -> dict:
    """Blend the BUY signals into one timing score with a confluence bonus.

    Returns {score, confluence, fired, est_hold_days, top_reason}.
    """
    weights = POSITIONAL_STRATEGY_WEIGHTS
    buy_sigs = [s for s in signals if s.action == "BUY"]

    if not buy_sigs:
        return {"score": 0.0, "confluence": 0, "fired": [],
                "est_hold_days": 15, "top_reason": ""}

    total_w = sum(weights.get(s.strategy, 0.05) for s in buy_sigs) or 1.0
    base = sum(weights.get(s.strategy, 0.05) * s.score for s in buy_sigs) / total_w

    confluence = len(buy_sigs)
    score = _clip(base + (confluence - 1) * POSITIONAL_CONFLUENCE_BONUS)

    hold = int(
        sum(weights.get(s.strategy, 0.05) * s.hold_days for s in buy_sigs) / total_w
    )
    top = max(buy_sigs, key=lambda s: s.score)
    return {
        "score": round(score, 1),
        "confluence": confluence,
        "fired": [s.strategy for s in buy_sigs],
        "est_hold_days": hold,
        "top_reason": top.reason,
    }


# ── Composite + horizon ─────────────────────────────────────────────────────

def _blend(pillars: Dict[str, Optional[float]], weights: Dict[str, float]) -> float:
    """Weighted average over the pillars that are present (value not None)."""
    num = den = 0.0
    for name, w in weights.items():
        v = pillars.get(name)
        if v is None:
            continue
        num += w * v
        den += w
    return round(num / den, 1) if den > 0 else 50.0


def classify_horizon(timing: float, durability: float) -> str:
    timing_strong = timing >= POSITIONAL_TIMING_STRONG
    durab_strong = durability >= POSITIONAL_DURABILITY_STRONG
    if timing_strong and durab_strong:
        return HORIZON_BOTH
    if timing_strong:
        return HORIZON_POSITIONAL
    if durab_strong:
        return HORIZON_LONG_TERM
    return HORIZON_AVOID


def recompute(
    *,
    timing: Optional[float],
    quality: Optional[float] = None,
    valuation: Optional[float] = None,
    momentum: Optional[float] = None,
    sentiment: Optional[float] = None,
    management: Optional[float] = None,
) -> dict:
    """Re-blend composite/durability/horizon from already-computed pillar values.

    Used by the Phase-3 research step to fold in the management pillar without
    re-running the strategies. Timing (Axis A) is unchanged, so a buy/no-buy
    decision can't flip here — but durability can cross the threshold and upgrade
    a POSITIONAL candidate to BOTH.
    """
    pillars: Dict[str, Optional[float]] = {
        "technical": timing, "quality": quality, "valuation": valuation,
        "momentum": momentum, "sentiment": sentiment, "management": management,
    }
    composite = _blend(pillars, POSITIONAL_PILLAR_WEIGHTS)
    durability = _blend(pillars, POSITIONAL_DURABILITY_WEIGHTS)
    horizon = classify_horizon(timing or 0.0, durability)
    return {"composite": composite, "durability": durability, "horizon": horizon}


def build_scorecard(
    ticker: str,
    price: float,
    signals: List[PositionalSignal],
    *,
    quality: Optional[float] = None,
    valuation: Optional[float] = None,
    momentum: Optional[float] = None,
    sentiment: Optional[float] = None,
    management: Optional[float] = None,
    min_composite: float = POSITIONAL_MIN_TREND_SCORE,
) -> Scorecard:
    """Aggregate strategy signals + context pillars into one Scorecard."""
    tech = technical_pillar(signals)

    pillars: Dict[str, Optional[float]] = {
        "technical": tech["score"],
        "quality": quality,
        "valuation": valuation,
        "momentum": momentum,
        "sentiment": sentiment,
    }
    if management is not None:
        pillars["management"] = management

    composite = _blend(pillars, POSITIONAL_PILLAR_WEIGHTS)

    timing = tech["score"]
    durability = _blend(pillars, POSITIONAL_DURABILITY_WEIGHTS)
    horizon = classify_horizon(timing, durability)

    # Entry is gated on TIMING (Axis A), not the durability-blended composite —
    # a positional trade's thesis is the setup, so a strong chart with average
    # fundamentals should still trigger. Durability only decides the horizon label.
    # LONG_TERM is a watch/accumulate candidate, not an immediate positional buy.
    if horizon in (HORIZON_BOTH, HORIZON_POSITIONAL) and timing >= min_composite:
        action = "BUY"
    elif horizon == HORIZON_LONG_TERM:
        action = "WATCH"
    elif tech["confluence"] >= 1:
        action = "WATCH"
    else:
        action = "HOLD"

    # Conviction
    high_count = sum(1 for s in signals if s.action == "BUY" and s.conviction == "high")
    if (tech["confluence"] >= 2 and durability >= POSITIONAL_DURABILITY_STRONG) or high_count >= 2:
        conviction = "high"
    elif tech["confluence"] >= 1:
        conviction = "medium"
    else:
        conviction = "low"

    reason = _summarise(ticker, horizon, tech, pillars, composite)

    return Scorecard(
        ticker=ticker,
        price=round(price, 2),
        action=action,
        horizon=horizon,
        conviction=conviction,
        composite_score=composite,
        timing_score=round(timing, 1),
        durability_score=round(durability, 1),
        confluence=tech["confluence"],
        strategies_fired=tech["fired"],
        est_hold_days=tech["est_hold_days"] or 15,
        pillars={k: round(v, 1) for k, v in pillars.items() if v is not None},
        signals=signals,
        reason=reason,
    )


def _summarise(ticker: str, horizon: str, tech: dict,
               pillars: Dict[str, Optional[float]], composite: float) -> str:
    fired = ", ".join(tech["fired"]) if tech["fired"] else "no entry trigger"
    label = {
        HORIZON_BOTH: "POSITIONAL + LONG-TERM",
        HORIZON_POSITIONAL: "POSITIONAL only",
        HORIZON_LONG_TERM: "LONG-TERM watch (no trigger yet)",
        HORIZON_AVOID: "avoid",
    }.get(horizon, horizon)
    parts = [
        f"[{label}] composite {composite:.0f}",
        f"{tech['confluence']}-strategy confluence ({fired})",
    ]
    pill_bits = []
    for name in ("quality", "valuation", "momentum", "sentiment", "management"):
        v = pillars.get(name)
        if v is not None:
            pill_bits.append(f"{name[:4]}={v:.0f}")
    if pill_bits:
        parts.append("pillars: " + " ".join(pill_bits))
    if tech["top_reason"]:
        parts.append(tech["top_reason"])
    return " | ".join(parts)[:600]

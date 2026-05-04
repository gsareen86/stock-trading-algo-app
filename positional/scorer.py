"""
Positional composite scorer.

Combines per-strategy PositionalSignal scores into a single composite score
using POSITIONAL_STRATEGY_WEIGHTS. Also computes a position-size-adjusted
conviction level.

Scoring formula per strategy:
  raw_score = signal.score if action == 'BUY' else (100 - signal.score) if action == 'SELL' else 50

Final composite = Σ (weight_i × raw_score_i) / Σ weight_i

Only strategies that produced a non-HOLD signal contribute their full weight.
HOLD signals contribute 50 (neutral) so the composite degrades gracefully
when only some strategies fire.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from config import POSITIONAL_MIN_COMPOSITE_SCORE, POSITIONAL_STRATEGY_WEIGHTS
from positional.strategies.base import PositionalSignal

log = logging.getLogger(__name__)


@dataclass
class PositionalDecision:
    ticker: str
    action: str                          # 'BUY' | 'SELL' | 'HOLD'
    composite_score: float
    price: float
    strategy_scores: Dict[str, float] = field(default_factory=dict)
    signals: List[PositionalSignal] = field(default_factory=list)
    top_reason: str = ""
    avg_hold_days: int = 15
    conviction: str = "medium"


def _signal_to_score(sig: PositionalSignal) -> float:
    """Convert action + score to a 0-100 directional score (50 = neutral)."""
    if sig.action == "BUY":
        return sig.score
    if sig.action == "SELL":
        return 100.0 - sig.score
    return 50.0  # HOLD


def evaluate_positional(
    ticker: str,
    signals: List[PositionalSignal],
    weights: Dict[str, float] | None = None,
) -> PositionalDecision:
    """Aggregate per-strategy signals into a single PositionalDecision."""
    weights = weights or POSITIONAL_STRATEGY_WEIGHTS
    total_weight = 0.0
    weighted_sum = 0.0
    strategy_scores: Dict[str, float] = {}

    for sig in signals:
        w = weights.get(sig.strategy, 0.0)
        if w <= 0:
            continue
        s = _signal_to_score(sig)
        weighted_sum += w * s
        total_weight += w
        strategy_scores[sig.strategy] = round(s, 1)

    if total_weight <= 0:
        return PositionalDecision(ticker, "HOLD", 50.0, 0.0,
                                  strategy_scores=strategy_scores,
                                  signals=signals,
                                  top_reason="no weighted strategies fired")

    composite = weighted_sum / total_weight

    # Determine action
    if composite >= POSITIONAL_MIN_COMPOSITE_SCORE:
        action = "BUY"
    elif composite <= (100 - POSITIONAL_MIN_COMPOSITE_SCORE):
        action = "SELL"
    else:
        action = "HOLD"

    # Top reason: highest-scoring non-HOLD signal
    non_hold = [s for s in signals if s.action != "HOLD"]
    top_sig = max(non_hold, key=lambda s: s.score, default=None) if non_hold else None
    top_reason = top_sig.reason if top_sig else "composite below threshold"

    # Weighted average hold days (BUY signals only)
    buy_sigs = [s for s in signals if s.action == action and s.action != "HOLD"]
    avg_hold = (
        int(sum(s.hold_days * weights.get(s.strategy, 1) for s in buy_sigs)
            / max(sum(weights.get(s.strategy, 1) for s in buy_sigs), 1))
        if buy_sigs else 15
    )

    # Conviction: how many high-conviction strategies agree
    high_count = sum(1 for s in buy_sigs if s.conviction == "high")
    conviction = "high" if high_count >= 2 else ("medium" if buy_sigs else "low")

    price = next((s.price for s in signals if s.price), 0.0)

    return PositionalDecision(
        ticker=ticker,
        action=action,
        composite_score=round(composite, 2),
        price=price or 0.0,
        strategy_scores=strategy_scores,
        signals=signals,
        top_reason=top_reason,
        avg_hold_days=avg_hold,
        conviction=conviction,
    )

"""
Composite scoring engine.
Blends technical (multi-strategy) + fundamental + sentiment into a 0-100 score,
then returns the final BUY/SELL/HOLD decision with reasoning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from config import (
    FUNDAMENTAL_WEIGHT,
    MIN_COMPOSITE_SCORE,
    MIN_FUNDAMENTAL_SCORE,
    SENTIMENT_BLOCK_THRESHOLD,
    SENTIMENT_WEIGHT,
    STRATEGY_WEIGHTS,
    TECHNICAL_WEIGHT,
)
from data.fundamentals import fetch_and_store, get_cached
from nlp.sentiment import aggregated_sentiment
from strategies import all_strategies, Signal

log = logging.getLogger(__name__)


@dataclass
class CompositeDecision:
    ticker: str
    action: str                    # BUY | SELL | HOLD
    composite_score: float
    technical_score: float
    fundamental_score: float
    sentiment_score: float         # -1..+1 raw
    price: Optional[float]
    signals: List[Signal]
    reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.action} {self.ticker} @ {self.price} "
            f"(composite={self.composite_score:.1f}, "
            f"tech={self.technical_score:.1f}, "
            f"fund={self.fundamental_score:.1f}, "
            f"sent={self.sentiment_score:+.2f})"
        )


def _aggregate_technical(signals: List[Signal]) -> tuple[str, float, List[str]]:
    """
    Vote across strategies, weighted. Returns (action, score, reason_list).
    - Sum weighted scores for BUY vs SELL directions.
    - Action = side with higher weighted sum; HOLD if neither clear.
    """
    buy_score = 0.0
    sell_score = 0.0
    hold_score = 0.0
    reasons = []
    for sig in signals:
        w = STRATEGY_WEIGHTS.get(sig.strategy, 0.25)
        if sig.action == "BUY":
            buy_score += sig.score * w
            reasons.append(f"[{sig.strategy} +{sig.score:.0f} w={w:.2f}] {sig.reason}")
        elif sig.action == "SELL":
            sell_score += sig.score * w
            reasons.append(f"[{sig.strategy} -{sig.score:.0f} w={w:.2f}] {sig.reason}")
        else:
            hold_score += sig.score * w

    # Net directional conviction
    net = buy_score - sell_score
    total = buy_score + sell_score + hold_score
    if total <= 0:
        return "HOLD", 50.0, reasons

    # Normalize: map (net, total) to 0-100 where 50 = neutral
    if abs(net) < 5:
        return "HOLD", 50.0 + net, reasons
    if net > 0:
        # higher conviction when strong buy and weak sell
        score = 50 + min(net, 50)
        return "BUY", round(score, 2), reasons
    else:
        score = 50 + min(-net, 50)
        return "SELL", round(score, 2), reasons


def evaluate(ticker: str, df: pd.DataFrame) -> CompositeDecision:
    """Build a composite decision for a single ticker."""
    strategies = all_strategies()
    signals = [s.generate(ticker, df) for s in strategies]

    action_t, tech_score, tech_reasons = _aggregate_technical(signals)

    # Fundamentals (cached)
    fund = get_cached(ticker) or fetch_and_store(ticker)
    if not fund:
        log.debug("fundamentals unavailable for %s, using neutral score 50.0", ticker)
    fund_score = float(fund.get("fundamental_score", 50.0)) if fund else 50.0

    # Sentiment
    sent_raw = aggregated_sentiment(ticker, hours=24)
    sent_score_0_100 = 50 + sent_raw * 50  # map -1..+1 -> 0..100

    # Composite score: only meaningful when technical direction is BUY; otherwise pass through.
    composite = (
        tech_score * TECHNICAL_WEIGHT
        + fund_score * FUNDAMENTAL_WEIGHT
        + sent_score_0_100 * SENTIMENT_WEIGHT
    )

    # Decision logic:
    # - BUY requires technical BUY, fundamental above floor, composite above cutoff,
    #   and non-strongly-negative sentiment.
    # - SELL propagates directly (we may want to exit even if fundamentals are good).
    action = "HOLD"
    reasons = tech_reasons[:]
    reasons.append(
        f"Fundamental={fund_score:.0f}  Sentiment={sent_raw:+.2f}  "
        f"Composite={composite:.1f}"
    )

    if action_t == "BUY":
        if fund_score < MIN_FUNDAMENTAL_SCORE:
            reasons.append(f"Blocked: fundamentals {fund_score:.0f} < {MIN_FUNDAMENTAL_SCORE}")
        elif composite < MIN_COMPOSITE_SCORE:
            reasons.append(f"Blocked: composite {composite:.0f} < {MIN_COMPOSITE_SCORE}")
        elif sent_raw < SENTIMENT_BLOCK_THRESHOLD:
            reasons.append(
                f"Blocked: very negative news sentiment "
                f"({sent_raw:+.2f} < {SENTIMENT_BLOCK_THRESHOLD:+.2f})"
            )
        else:
            action = "BUY"
    elif action_t == "SELL":
        action = "SELL"

    price = next((s.price for s in signals if s.price is not None), None)

    return CompositeDecision(
        ticker=ticker,
        action=action,
        composite_score=round(composite, 2),
        technical_score=round(tech_score, 2),
        fundamental_score=round(fund_score, 2),
        sentiment_score=round(sent_raw, 3),
        price=price,
        signals=signals,
        reasons=reasons,
    )


def evaluate_batch(candles: Dict[str, pd.DataFrame]) -> List[CompositeDecision]:
    out = []
    for ticker, df in candles.items():
        try:
            out.append(evaluate(ticker, df))
        except Exception as e:
            log.warning("evaluate failed for %s: %s", ticker, e)
    return out

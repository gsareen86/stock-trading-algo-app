"""
Quality-Momentum strategy.

Combines fundamental quality (from lt_quality scorer) with price momentum:
  * Quality score ≥ 70 / 100  — profitability, cash quality, solvency, growth
  * 63-day (≈3-month) return  ≥ 15% — price momentum is already strong
  * RSI(14) crosses above 50 from below — momentum just turned up from a trough

This is the highest-conviction strategy because fundamentally sound businesses
being actively bought by institutions (smart money driving the momentum) have
persistent forward returns.

The quality_score parameter is injected by the scorer/screener from lt_quality.
If unavailable it defaults to 50 (neutral) so the strategy still runs on
momentum alone, just with a lower score ceiling.
"""
from __future__ import annotations

import pandas as pd

from config import (
    POS_MOMENTUM_63D_MIN_PCT,
    POS_QUALITY_MIN_SCORE,
    POS_RSI_ENTRY_LEVEL,
    POS_RSI_PERIOD,
)
from positional.strategies.base import BasePositionalStrategy, PositionalSignal


class QualityMomentumStrategy(BasePositionalStrategy):
    name = "quality_momentum"

    def __init__(
        self,
        quality_min: float = POS_QUALITY_MIN_SCORE,
        momentum_min_pct: float = POS_MOMENTUM_63D_MIN_PCT,
        rsi_entry: float = POS_RSI_ENTRY_LEVEL,
        rsi_period: int = POS_RSI_PERIOD,
    ):
        self.quality_min = quality_min
        self.momentum_min_pct = momentum_min_pct
        self.rsi_entry = rsi_entry
        self.rsi_period = rsi_period

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        if df is None or len(df) < 70:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason="insufficient data")

        close = df["Close"].astype(float)
        price = float(close.iloc[-1])

        # Quality gate
        if quality_score < self.quality_min:
            return PositionalSignal(
                ticker, "HOLD", self.name, 45.0, price,
                reason=f"quality score {quality_score:.1f} < {self.quality_min}",
            )

        # 63-day momentum
        if len(close) < 64:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="need 64+ bars for 63d momentum")
        price_63d_ago = float(close.iloc[-64])
        if price_63d_ago <= 0:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason="invalid historical price")
        momentum_63d = (price - price_63d_ago) / price_63d_ago * 100

        if momentum_63d < self.momentum_min_pct:
            return PositionalSignal(
                ticker, "HOLD", self.name, 50.0, price,
                reason=f"63d momentum {momentum_63d:.1f}% < {self.momentum_min_pct}%",
            )

        # RSI cross above entry level
        rsi = self._rsi(close, self.rsi_period)
        rsi_now = float(rsi.iloc[-1])
        rsi_prev = float(rsi.iloc[-2])

        # Must cross above rsi_entry from below within last 5 bars
        crossed_up = rsi_prev < self.rsi_entry <= rsi_now
        recently_crossed = any(
            float(rsi.iloc[-(i + 2)]) < self.rsi_entry <= float(rsi.iloc[-(i + 1)])
            for i in range(1, min(5, len(rsi) - 1))
        )

        if not (crossed_up or recently_crossed):
            return PositionalSignal(
                ticker, "HOLD", self.name, 55.0, price,
                reason=(f"RSI={rsi_now:.1f} — waiting for cross above {self.rsi_entry} "
                        f"(63d mom={momentum_63d:.1f}%)"),
            )

        q_premium = (quality_score - self.quality_min) / 30  # 0-1 above floor
        mom_premium = min((momentum_63d - self.momentum_min_pct) / 30, 1.0)
        score = self._clip(70 + q_premium * 15 + mom_premium * 10)

        return PositionalSignal(
            ticker, "BUY", self.name, score, price,
            hold_days=20,
            conviction="high" if quality_score >= 80 else "medium",
            reason=(f"Quality-momentum: Q={quality_score:.0f}/100, "
                    f"63d={momentum_63d:.1f}%, RSI={rsi_now:.1f} crossed {self.rsi_entry}"),
            meta={
                "quality_score": quality_score,
                "momentum_63d_pct": round(momentum_63d, 2),
                "rsi": round(rsi_now, 1),
            },
        )

"""
EMA Ribbon + ADX trend-following strategy.

Bull setup: 9-EMA > 21-EMA > 55-EMA with ADX(14) > 25 — strong trending market.
Entry on pullback to 21-EMA (price within 1% of mid EMA) or reclaim candle
(previous close below 21-EMA, current close above it).

Bear setup: same ribbon inverted. Emits SELL for short positional entries.
"""
from __future__ import annotations

import pandas as pd

from config import (
    POS_ADX_PERIOD,
    POS_ADX_THRESHOLD,
    POS_EMA_FAST,
    POS_EMA_MID,
    POS_EMA_SLOW,
)
from positional.strategies.base import BasePositionalStrategy, PositionalSignal


class TrendFollowingStrategy(BasePositionalStrategy):
    name = "trend_following"

    def __init__(
        self,
        ema_fast: int = POS_EMA_FAST,
        ema_mid: int = POS_EMA_MID,
        ema_slow: int = POS_EMA_SLOW,
        adx_period: int = POS_ADX_PERIOD,
        adx_threshold: float = POS_ADX_THRESHOLD,
    ):
        self.ema_fast = ema_fast
        self.ema_mid = ema_mid
        self.ema_slow = ema_slow
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        if df is None or len(df) < self.ema_slow + 20:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason="insufficient data")

        close = df["Close"].astype(float)
        ema_f = self._ema(close, self.ema_fast)
        ema_m = self._ema(close, self.ema_mid)
        ema_s = self._ema(close, self.ema_slow)
        adx = self._adx(df, self.adx_period)

        price = float(close.iloc[-1])
        ef, em, es = float(ema_f.iloc[-1]), float(ema_m.iloc[-1]), float(ema_s.iloc[-1])
        adx_val = float(adx.iloc[-1])
        prev_close = float(close.iloc[-2])
        prev_em = float(ema_m.iloc[-2])

        bull_ribbon = ef > em > es
        bear_ribbon = ef < em < es
        strong = adx_val > self.adx_threshold

        near_mid = abs(price - em) / (em + 1e-10) < 0.012
        reclaim = prev_close < prev_em <= price  # closed back above mid EMA today

        if bull_ribbon and strong and (near_mid or reclaim):
            strength = min((adx_val - self.adx_threshold) / 25.0, 1.0)
            q_boost = (quality_score - 50) / 100  # ±0.5
            score = self._clip(65 + strength * 20 + q_boost * 5)
            conviction = "high" if adx_val > 35 else "medium"
            return PositionalSignal(
                ticker, "BUY", self.name, score, price,
                hold_days=15,
                conviction=conviction,
                reason=(f"Bull EMA ribbon (9>{em:.0f}>55) ADX={adx_val:.1f} "
                        f"{'reclaim' if reclaim else 'pullback'} entry"),
                meta={"ema_fast": ef, "ema_mid": em, "ema_slow": es, "adx": adx_val},
            )

        if bear_ribbon and strong:
            strength = min((adx_val - self.adx_threshold) / 25.0, 1.0)
            score = self._clip(65 + strength * 15)
            return PositionalSignal(
                ticker, "SELL", self.name, score, price,
                hold_days=10,
                conviction="medium",
                reason=f"Bear EMA ribbon ADX={adx_val:.1f}",
                meta={"ema_fast": ef, "ema_mid": em, "ema_slow": es, "adx": adx_val},
            )

        return PositionalSignal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=(f"No ribbon signal — ADX={adx_val:.1f} "
                    f"bull={bull_ribbon} bear={bear_ribbon}"),
        )

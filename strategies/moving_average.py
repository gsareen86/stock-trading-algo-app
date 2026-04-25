"""
EMA crossover strategy.
BUY  when fast EMA (20) crosses above slow EMA (50) with positive slope on slow.
SELL when fast EMA crosses below slow EMA.
"""
from __future__ import annotations

import pandas as pd
from ta.trend import EMAIndicator

from strategies.base import BaseStrategy, Signal


class EMACrossoverStrategy(BaseStrategy):
    name = "ema_crossover"

    def __init__(self, fast: int = 20, slow: int = 50):
        self.fast = fast
        self.slow = slow

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        if df is None or len(df) < self.slow + 2:
            return Signal(ticker, "HOLD", self.name, 50.0, reason="insufficient data")

        close = df["Close"]
        fast = EMAIndicator(close=close, window=self.fast).ema_indicator()
        slow = EMAIndicator(close=close, window=self.slow).ema_indicator()

        last = -1
        prev = -2
        f_now, f_prev = float(fast.iloc[last]), float(fast.iloc[prev])
        s_now, s_prev = float(slow.iloc[last]), float(slow.iloc[prev])
        price = float(close.iloc[last])

        # Magnitude of separation scaled by price, to rank signals.
        sep_pct = (f_now - s_now) / s_now * 100 if s_now else 0
        slope_slow = (s_now - s_prev) / s_prev * 100 if s_prev else 0

        if f_prev <= s_prev and f_now > s_now:
            # Fresh bullish cross
            score = self._clip(65 + min(sep_pct * 10, 25) + max(slope_slow * 5, 0))
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=f"EMA{self.fast}>{self.slow} cross (sep {sep_pct:+.2f}%, slope {slope_slow:+.2f}%)",
                meta={"ema_fast": f_now, "ema_slow": s_now},
            )
        if f_prev >= s_prev and f_now < s_now:
            score = self._clip(65 + min(-sep_pct * 10, 25))
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=f"EMA{self.fast}<{self.slow} cross (sep {sep_pct:+.2f}%)",
                meta={"ema_fast": f_now, "ema_slow": s_now},
            )

        # No cross — gentle directional bias
        bias = 50 + min(max(sep_pct * 5, -20), 20)
        return Signal(
            ticker, "HOLD", self.name, self._clip(bias), price,
            reason=f"no EMA cross (sep {sep_pct:+.2f}%)",
        )

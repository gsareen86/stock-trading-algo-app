"""
RSI mean-reversion strategy.
BUY  on RSI < 30 (oversold) rising.
SELL on RSI > 70 (overbought) falling.
"""
from __future__ import annotations

import pandas as pd
from ta.momentum import RSIIndicator

from strategies.base import BaseStrategy, Signal


class RSIMeanReversionStrategy(BaseStrategy):
    name = "rsi_mean_reversion"

    def __init__(self, period: int = 14, oversold: int = 30, overbought: int = 70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        if df is None or len(df) < self.period + 2:
            return Signal(ticker, "HOLD", self.name, 50.0, reason="insufficient data")

        close = df["Close"]
        rsi = RSIIndicator(close=close, window=self.period).rsi()
        rsi_now = float(rsi.iloc[-1])
        rsi_prev = float(rsi.iloc[-2])
        price = float(close.iloc[-1])

        if rsi_now < self.oversold and rsi_now > rsi_prev:
            depth = self.oversold - rsi_now
            score = self._clip(60 + depth * 2)
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=f"RSI oversold rising ({rsi_prev:.1f}→{rsi_now:.1f})",
                meta={"rsi": rsi_now},
            )
        if rsi_now > self.overbought and rsi_now < rsi_prev:
            height = rsi_now - self.overbought
            score = self._clip(60 + height * 2)
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=f"RSI overbought falling ({rsi_prev:.1f}→{rsi_now:.1f})",
                meta={"rsi": rsi_now},
            )

        # Neutral
        return Signal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=f"RSI neutral ({rsi_now:.1f})",
            meta={"rsi": rsi_now},
        )

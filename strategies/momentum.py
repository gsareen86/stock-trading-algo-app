"""
Price+volume momentum strategy.
Ranks stocks on short-term return * volume surge, confirmed by MACD direction.
"""
from __future__ import annotations

import pandas as pd
from ta.trend import MACD

from strategies.base import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):
    name = "momentum"

    def __init__(self, lookback: int = 10):
        self.lookback = lookback

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        if df is None or len(df) < max(self.lookback + 2, 35):
            return Signal(ticker, "HOLD", self.name, 50.0, reason="insufficient data")

        close = df["Close"]
        volume = df["Volume"]

        ret_n = (close.iloc[-1] / close.iloc[-self.lookback] - 1) * 100
        vol_now = float(volume.iloc[-1])
        vol_avg = float(volume.iloc[-self.lookback:].mean())
        vol_ratio = (vol_now / vol_avg) if vol_avg else 1.0

        macd = MACD(close=close)
        macd_line = macd.macd()
        sig_line = macd.macd_signal()
        hist_now = float(macd_line.iloc[-1] - sig_line.iloc[-1])
        hist_prev = float(macd_line.iloc[-2] - sig_line.iloc[-2])

        price = float(close.iloc[-1])

        # Bullish confluence
        if ret_n > 2.0 and hist_now > 0 and hist_now > hist_prev and vol_ratio > 1.1:
            score = self._clip(60 + min(ret_n * 2, 25) + min(vol_ratio * 5, 10))
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=f"Momentum+ ({ret_n:+.2f}% over {self.lookback}, vol {vol_ratio:.2f}x)",
                meta={"ret_n": ret_n, "macd_hist": hist_now},
            )
        # Bearish confluence
        if ret_n < -2.0 and hist_now < 0 and hist_now < hist_prev and vol_ratio > 1.1:
            score = self._clip(60 + min(-ret_n * 2, 25))
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=f"Momentum- ({ret_n:+.2f}% over {self.lookback})",
                meta={"ret_n": ret_n, "macd_hist": hist_now},
            )

        return Signal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=f"no momentum ({ret_n:+.2f}%)",
            meta={"ret_n": ret_n},
        )

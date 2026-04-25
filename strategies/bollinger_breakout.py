"""
Bollinger-band breakout with volume confirmation.
BUY on upper-band breakout backed by above-average volume.
SELL on lower-band breakdown with above-average volume.
"""
from __future__ import annotations

import pandas as pd
from ta.volatility import BollingerBands

from strategies.base import BaseStrategy, Signal


class BollingerBreakoutStrategy(BaseStrategy):
    name = "bollinger_breakout"

    def __init__(self, period: int = 20, std: float = 2.0, vol_mult: float = 1.3):
        self.period = period
        self.std = std
        self.vol_mult = vol_mult

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        if df is None or len(df) < self.period + 5:
            return Signal(ticker, "HOLD", self.name, 50.0, reason="insufficient data")

        close = df["Close"]
        volume = df["Volume"]
        bb = BollingerBands(close=close, window=self.period, window_dev=self.std)
        upper = bb.bollinger_hband()
        lower = bb.bollinger_lband()
        mid = bb.bollinger_mavg()

        price = float(close.iloc[-1])
        upper_now = float(upper.iloc[-1])
        lower_now = float(lower.iloc[-1])
        mid_now = float(mid.iloc[-1])
        vol_now = float(volume.iloc[-1])
        vol_avg = float(volume.iloc[-self.period:].mean())
        vol_ratio = (vol_now / vol_avg) if vol_avg else 1.0

        # Band width (volatility) normalized
        band_width = (upper_now - lower_now) / mid_now * 100 if mid_now else 0

        if price > upper_now and vol_ratio > self.vol_mult:
            score = self._clip(65 + min(vol_ratio * 5, 20) + min(band_width, 10))
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=f"Upper-band breakout (vol {vol_ratio:.2f}x avg)",
                meta={"upper": upper_now, "volume_ratio": vol_ratio},
            )
        if price < lower_now and vol_ratio > self.vol_mult:
            score = self._clip(65 + min(vol_ratio * 5, 20))
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=f"Lower-band breakdown (vol {vol_ratio:.2f}x avg)",
                meta={"lower": lower_now, "volume_ratio": vol_ratio},
            )

        return Signal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=f"price within bands (vol {vol_ratio:.2f}x)",
            meta={"volume_ratio": vol_ratio},
        )

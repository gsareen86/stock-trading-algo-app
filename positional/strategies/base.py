"""Base class and signal dataclass for positional strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class PositionalSignal:
    ticker: str
    action: str                      # 'BUY' | 'SELL' | 'HOLD'
    strategy: str
    score: float = 0.0               # 0-100; 100 = maximum conviction BUY
    price: Optional[float] = None
    reason: str = ""
    hold_days: int = 15              # expected hold period in trading days
    conviction: str = "medium"       # 'low' | 'medium' | 'high'
    meta: dict = field(default_factory=dict)


class BasePositionalStrategy:
    name: str = "base_positional"

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        raise NotImplementedError

    @staticmethod
    def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
        return max(lo, min(hi, x))

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        close = df["Close"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        return tr.ewm(com=period - 1, adjust=False).mean()

    @staticmethod
    def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        close = df["Close"].astype(float)
        prev_close = close.shift(1)
        prev_high = high.shift(1)
        prev_low = low.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        dm_pos = (high - prev_high).clip(lower=0)
        dm_neg = (prev_low - low).clip(lower=0)
        dm_pos = dm_pos.where(dm_pos > dm_neg, 0)
        dm_neg = dm_neg.where(dm_neg > dm_pos, 0)
        atr_s = tr.ewm(com=period - 1, adjust=False).mean()
        di_pos = 100 * dm_pos.ewm(com=period - 1, adjust=False).mean() / (atr_s + 1e-10)
        di_neg = 100 * dm_neg.ewm(com=period - 1, adjust=False).mean() / (atr_s + 1e-10)
        dx = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg + 1e-10)
        return dx.ewm(com=period - 1, adjust=False).mean()

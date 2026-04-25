"""
Strategy base class + Signal dataclass.
Each concrete strategy reads a price DataFrame and emits a Signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class Signal:
    ticker: str
    action: str                    # 'BUY' | 'SELL' | 'HOLD'
    strategy: str
    score: float = 0.0             # technical score 0-100 (100 = strongest buy)
    price: Optional[float] = None
    reason: str = ""
    meta: dict = field(default_factory=dict)


class BaseStrategy:
    """Subclasses should implement `.generate(ticker, df)` returning a Signal."""

    name: str = "base"

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        raise NotImplementedError

    @staticmethod
    def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
        return max(lo, min(hi, x))

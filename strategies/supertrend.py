"""
Supertrend — ATR-based trend follower with built-in directional regime.

Supertrend computes upper/lower bands offset from the median price by
``multiplier * ATR``. The active trend flips when price crosses the band
that's currently in force. The output is an unambiguous LONG / SHORT
regime per bar plus a trailing stop.

We emit:
  * BUY  when the bar that just closed flipped the regime to LONG.
  * SELL when the bar that just closed flipped the regime to SHORT.
  * HOLD with directional bias score otherwise.

Pairs naturally with the existing momentum strategy: when both agree on
direction the composite score gets a confluence boost.

Reference implementation follows the canonical Olivier Seban / TradingView
formulation. Wilder ATR for stability.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import SUPERTREND_MULT, SUPERTREND_PERIOD
from strategies.base import BaseStrategy, Signal


def _wilder_atr(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _supertrend(df: pd.DataFrame, period: int, multiplier: float) -> pd.DataFrame:
    """Return df with columns: ``supertrend`` (level) and ``trend`` (+1/-1)."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    atr = _wilder_atr(df, period)
    hl2 = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    n = len(df)
    final_upper = upper.copy()
    final_lower = lower.copy()
    trend = np.ones(n, dtype=int)  # +1 long regime, -1 short regime
    st = np.full(n, np.nan, dtype=float)

    for i in range(1, n):
        # Upper band can only ratchet down (or stay) while in short regime.
        if upper.iloc[i] < final_upper.iloc[i - 1] or close.iloc[i - 1] > final_upper.iloc[i - 1]:
            final_upper.iloc[i] = upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i - 1]
        # Lower band can only ratchet up while in long regime.
        if lower.iloc[i] > final_lower.iloc[i - 1] or close.iloc[i - 1] < final_lower.iloc[i - 1]:
            final_lower.iloc[i] = lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i - 1]

        # Regime flips when price crosses the active band.
        prev_trend = trend[i - 1]
        if prev_trend == 1:
            if close.iloc[i] < final_lower.iloc[i]:
                trend[i] = -1
            else:
                trend[i] = 1
        else:
            if close.iloc[i] > final_upper.iloc[i]:
                trend[i] = 1
            else:
                trend[i] = -1
        st[i] = final_lower.iloc[i] if trend[i] == 1 else final_upper.iloc[i]

    return pd.DataFrame(
        {"supertrend": st, "trend": trend},
        index=df.index,
    )


class SupertrendStrategy(BaseStrategy):
    name = "supertrend"

    def __init__(self, period: int = SUPERTREND_PERIOD,
                 multiplier: float = SUPERTREND_MULT):
        self.period = period
        self.multiplier = multiplier

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        if df is None or len(df) < self.period + 5:
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason="insufficient data")

        st = _supertrend(df, self.period, self.multiplier)
        trend_now = int(st["trend"].iloc[-1])
        trend_prev = int(st["trend"].iloc[-2])
        st_level = float(st["supertrend"].iloc[-1])
        price = float(df["Close"].iloc[-1])

        # Distance from the trailing-stop level — used as conviction proxy.
        dist_pct = abs(price - st_level) / price * 100 if price else 0

        if trend_now == 1 and trend_prev == -1:
            # Fresh flip to long
            score = self._clip(65 + min(dist_pct * 5, 25))
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=(f"Supertrend flip → LONG @ {price:.2f}, "
                        f"trail {st_level:.2f} ({dist_pct:.2f}%)"),
                meta={"supertrend": st_level, "trend": 1},
            )
        if trend_now == -1 and trend_prev == 1:
            score = self._clip(65 + min(dist_pct * 5, 25))
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=(f"Supertrend flip → SHORT @ {price:.2f}, "
                        f"trail {st_level:.2f} ({dist_pct:.2f}%)"),
                meta={"supertrend": st_level, "trend": -1},
            )

        # No flip — emit a directional HOLD with a directional bias score so
        # the composite scorer can see the trend even when no fresh signal.
        bias = 50 + (10 if trend_now == 1 else -10)
        return Signal(
            ticker, "HOLD", self.name, self._clip(bias), price,
            reason=(f"Supertrend continuation "
                    f"({'long' if trend_now == 1 else 'short'}), "
                    f"trail {st_level:.2f}"),
            meta={"supertrend": st_level, "trend": trend_now},
        )

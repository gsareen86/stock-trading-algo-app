"""
Volatility Contraction Pattern (VCP) breakout — Mark Minervini style.

After a 3–6 month base, a stock shows a series of progressively tighter
price corrections (each smaller than the last by ≥15%). Volume dries up in
the final contraction. When price breaks the most recent pivot high on
expanding volume, the path of least resistance is up.

Detection algorithm:
1. Identify a base period (POS_VCP_BASE_MIN_DAYS to POS_VCP_BASE_MAX_DAYS bars).
2. Within the base, find alternating local highs/lows (swings).
3. Measure each correction (from swing-high to next swing-low) in %.
4. Each correction must be ≤ POS_VCP_CONTRACTION_RATIO × prior correction.
5. At least 2 such contracting corrections required.
6. Volume in the last 5 bars must be below POS_VCP_VOLUME_DRY_RATIO × 20-day avg.
7. Entry: today's close > most recent pivot high on volume > 1.5× avg.
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from config import (
    POS_VCP_BASE_MAX_DAYS,
    POS_VCP_BASE_MIN_DAYS,
    POS_VCP_BREAKOUT_VOL_MULT,
    POS_VCP_CONTRACTION_RATIO,
    POS_VCP_VOLUME_DRY_RATIO,
)
from positional.strategies.base import BasePositionalStrategy, PositionalSignal


def _local_extrema(series: pd.Series, order: int = 3) -> Tuple[List[int], List[int]]:
    """Return indices of local maxima and minima using a simple window comparison."""
    highs, lows = [], []
    vals = series.values
    n = len(vals)
    for i in range(order, n - order):
        window_l = vals[i - order: i]
        window_r = vals[i + 1: i + order + 1]
        if vals[i] >= max(window_l) and vals[i] >= max(window_r):
            highs.append(i)
        if vals[i] <= min(window_l) and vals[i] <= min(window_r):
            lows.append(i)
    return highs, lows


def _detect_vcp(close: pd.Series, high: pd.Series, low: pd.Series,
                base_start: int, contraction_ratio: float) -> Tuple[bool, float, List[float]]:
    """
    Returns (vcp_found, pivot_high, corrections_list).
    base_start is the index (from 0) where the base begins.
    """
    base_close = close.iloc[base_start:]
    base_high = high.iloc[base_start:]
    base_low = low.iloc[base_start:]

    h_idx, l_idx = _local_extrema(base_close, order=3)
    if len(h_idx) < 2 or len(l_idx) < 2:
        return False, 0.0, []

    # Build corrections: swing_high → next_swing_low
    corrections: List[float] = []
    pivot_highs: List[float] = []
    for hi in h_idx:
        subsequent_lows = [li for li in l_idx if li > hi]
        if not subsequent_lows:
            continue
        li = subsequent_lows[0]
        h_val = float(base_high.iloc[hi])
        l_val = float(base_low.iloc[li])
        if h_val > 0:
            corr_pct = (h_val - l_val) / h_val * 100
            corrections.append(corr_pct)
            pivot_highs.append(h_val)

    if len(corrections) < 2:
        return False, 0.0, []

    # Check contracting series: each correction < contraction_ratio × prior
    is_contracting = all(
        corrections[i] <= contraction_ratio * corrections[i - 1]
        for i in range(1, len(corrections))
    )

    if not is_contracting:
        return False, 0.0, []

    most_recent_pivot = float(max(pivot_highs[-2:])) if pivot_highs else 0.0
    return True, most_recent_pivot, corrections


class VCPBreakoutStrategy(BasePositionalStrategy):
    name = "vcp_breakout"

    def __init__(
        self,
        base_min: int = POS_VCP_BASE_MIN_DAYS,
        base_max: int = POS_VCP_BASE_MAX_DAYS,
        contraction_ratio: float = POS_VCP_CONTRACTION_RATIO,
        vol_dry_ratio: float = POS_VCP_VOLUME_DRY_RATIO,
        breakout_vol_mult: float = POS_VCP_BREAKOUT_VOL_MULT,
    ):
        self.base_min = base_min
        self.base_max = base_max
        self.contraction_ratio = contraction_ratio
        self.vol_dry_ratio = vol_dry_ratio
        self.breakout_vol_mult = breakout_vol_mult

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        needed = self.base_max + 30
        if df is None or len(df) < needed:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason=f"need {needed}+ bars")

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float)
        price = float(close.iloc[-1])

        # Try base windows from min to max (scan for any qualifying VCP)
        vcp_found = False
        pivot_high = 0.0
        best_corrections: List[float] = []

        for base_len in range(self.base_min, min(self.base_max, len(df) - 5) + 1, 5):
            base_start_idx = len(df) - base_len - 1
            if base_start_idx < 0:
                continue
            found, ph, corrs = _detect_vcp(
                close, high, low, base_start_idx, self.contraction_ratio
            )
            if found and ph > 0:
                vcp_found = True
                pivot_high = ph
                best_corrections = corrs
                break  # take the shortest qualifying base

        if not vcp_found:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="no VCP pattern detected")

        # Volume dry-up check: last 5 bars vs 20-day avg
        vol_20d = float(volume.iloc[-21:-1].mean()) or 1.0
        vol_5d_avg = float(volume.iloc[-6:-1].mean()) or 1.0
        vol_dry = vol_5d_avg / vol_20d < self.vol_dry_ratio

        if not vol_dry:
            return PositionalSignal(ticker, "HOLD", self.name, 55.0, price,
                                    reason=f"VCP found but volume not drying up "
                                           f"({vol_5d_avg/vol_20d:.2f}× avg)")

        # Breakout check: today's close > pivot high on expanding volume
        today_vol_ratio = float(volume.iloc[-1]) / vol_20d
        if price > pivot_high and today_vol_ratio >= self.breakout_vol_mult:
            n_stages = len(best_corrections)
            tightness = best_corrections[-1] if best_corrections else 5.0
            score = self._clip(68 + n_stages * 4 + max(0, 5 - tightness) * 2
                               + (quality_score - 50) / 20)
            return PositionalSignal(
                ticker, "BUY", self.name, score, price,
                hold_days=15,
                conviction="high" if n_stages >= 3 else "medium",
                reason=(f"VCP breakout: {n_stages} contracting stages "
                        f"({[f'{c:.1f}%' for c in best_corrections]}), "
                        f"pivot={pivot_high:.2f}, vol={today_vol_ratio:.2f}×"),
                meta={
                    "pivot_high": pivot_high,
                    "corrections": best_corrections,
                    "vol_ratio": round(today_vol_ratio, 2),
                },
            )

        # Pattern valid but no breakout yet — return HOLD with elevated score
        return PositionalSignal(
            ticker, "HOLD", self.name, 58.0, price,
            reason=(f"VCP pattern valid (pivot={pivot_high:.2f}) — "
                    f"awaiting breakout close (price={price:.2f}, "
                    f"vol={today_vol_ratio:.2f}×)"),
        )

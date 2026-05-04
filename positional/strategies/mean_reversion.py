"""
Mean-Reversion on Quality Stocks.

Thesis: high-quality businesses (quality score > 65) that suffer temporary
sell-downs of 15–25% from their 52-week high and show institutional
accumulation signals (volume spike + RSI divergence) tend to revert over 8–15 days.

Entry conditions:
  1. Quality score ≥ POS_MR_MIN_QUALITY_SCORE (filters out broken companies)
  2. Current price 15–25% below 52-week high (bands out breakdowns and shallow dips)
  3. RSI(14) < POS_MR_RSI_THRESHOLD (oversold territory)
  4. Last 3-bar average volume > POS_MR_VOL_SPIKE_MULT × 20-day avg
     (institutional accumulation)

Exclusion: if the sell-off coincides with a recent earnings miss or the drop
exceeds 25%, skip — those are structural breaks, not mean-reversion opportunities.
"""
from __future__ import annotations

import pandas as pd

from config import (
    POS_MR_BELOW_52W_MAX_PCT,
    POS_MR_BELOW_52W_MIN_PCT,
    POS_MR_MIN_QUALITY_SCORE,
    POS_MR_RSI_THRESHOLD,
    POS_MR_VOL_SPIKE_MULT,
    POS_RSI_PERIOD,
)
from positional.strategies.base import BasePositionalStrategy, PositionalSignal


class MeanReversionStrategy(BasePositionalStrategy):
    name = "mean_reversion"

    def __init__(
        self,
        below_52w_min: float = POS_MR_BELOW_52W_MIN_PCT,
        below_52w_max: float = POS_MR_BELOW_52W_MAX_PCT,
        rsi_threshold: float = POS_MR_RSI_THRESHOLD,
        vol_spike_mult: float = POS_MR_VOL_SPIKE_MULT,
        min_quality: float = POS_MR_MIN_QUALITY_SCORE,
        rsi_period: int = POS_RSI_PERIOD,
    ):
        self.below_52w_min = below_52w_min / 100
        self.below_52w_max = below_52w_max / 100
        self.rsi_threshold = rsi_threshold
        self.vol_spike_mult = vol_spike_mult
        self.min_quality = min_quality
        self.rsi_period = rsi_period

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        if df is None or len(df) < 30:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason="insufficient data")

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        volume = df["Volume"].astype(float)
        price = float(close.iloc[-1])

        # Quality gate
        if quality_score < self.min_quality:
            return PositionalSignal(
                ticker, "HOLD", self.name, 45.0, price,
                reason=f"quality {quality_score:.0f} < {self.min_quality} — skip broken cos",
            )

        # 52W high (excluding today)
        week52_high = float(high.iloc[:-1].max()) if len(high) > 1 else float(high.max())
        if week52_high <= 0:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason="invalid 52W high")

        pct_below = (week52_high - price) / week52_high

        # Band filter: 15–25% below 52W high
        if pct_below < self.below_52w_min:
            return PositionalSignal(
                ticker, "HOLD", self.name, 50.0, price,
                reason=f"only {pct_below*100:.1f}% below 52W high — not oversold enough",
            )
        if pct_below > self.below_52w_max:
            return PositionalSignal(
                ticker, "HOLD", self.name, 40.0, price,
                reason=f"{pct_below*100:.1f}% below 52W high — potential breakdown, skip",
            )

        # RSI oversold
        rsi = self._rsi(close, self.rsi_period)
        rsi_now = float(rsi.iloc[-1])
        if rsi_now >= self.rsi_threshold:
            return PositionalSignal(
                ticker, "HOLD", self.name, 50.0, price,
                reason=f"RSI={rsi_now:.1f} not yet oversold (< {self.rsi_threshold})",
            )

        # Volume spike: 3-bar avg > vol_spike_mult × 20-day avg
        vol_20d = float(volume.iloc[-21:-1].mean()) or 1.0
        vol_3d = float(volume.iloc[-4:-1].mean()) or 0.0
        vol_ratio = vol_3d / vol_20d

        if vol_ratio < self.vol_spike_mult:
            return PositionalSignal(
                ticker, "HOLD", self.name, 52.0, price,
                reason=(f"Oversold (RSI={rsi_now:.1f}, -{pct_below*100:.1f}%) "
                        f"but no volume spike ({vol_ratio:.2f}× avg)"),
            )

        depth_score = (pct_below - self.below_52w_min) / (self.below_52w_max - self.below_52w_min)
        oversold_score = (self.rsi_threshold - rsi_now) / self.rsi_threshold
        q_boost = (quality_score - self.min_quality) / 35
        score = self._clip(65 + depth_score * 10 + oversold_score * 10 + q_boost * 10)

        return PositionalSignal(
            ticker, "BUY", self.name, score, price,
            hold_days=10,
            conviction="medium",
            reason=(f"Mean reversion: -{pct_below*100:.1f}% from 52W high "
                    f"({week52_high:.2f}), RSI={rsi_now:.1f}, "
                    f"vol spike {vol_ratio:.2f}×, Q={quality_score:.0f}"),
            meta={
                "week52_high": week52_high,
                "pct_below": round(pct_below * 100, 2),
                "rsi": round(rsi_now, 1),
                "vol_spike_ratio": round(vol_ratio, 2),
                "quality_score": quality_score,
            },
        )

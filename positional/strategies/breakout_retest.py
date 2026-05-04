"""
52-Week High Breakout + Retest strategy.

Phase 1 — Breakout: stock closes above its 52-week high on volume > 1.5× avg.
Phase 2 — Retest: after the breakout the stock pulls back but holds above the
  old 52W high (±2%). Today's close re-enters the breakout zone (within 2% of
  the 52W high). This is the high-probability entry — the prior resistance
  becomes support.

Only fires if the pullback from the 52W high is ≤ 5% (deeper = breakdown risk).
Volume on the retest day should be lower (institutional supply has dried up).
"""
from __future__ import annotations

import pandas as pd

from config import (
    POS_BREAKOUT_52W_PROXIMITY_PCT,
    POS_BREAKOUT_MAX_PULLBACK_PCT,
    POS_BREAKOUT_VOL_MULT,
)
from positional.strategies.base import BasePositionalStrategy, PositionalSignal


class BreakoutRetestStrategy(BasePositionalStrategy):
    name = "breakout_retest"

    def __init__(
        self,
        proximity_pct: float = POS_BREAKOUT_52W_PROXIMITY_PCT,
        max_pullback_pct: float = POS_BREAKOUT_MAX_PULLBACK_PCT,
        vol_mult: float = POS_BREAKOUT_VOL_MULT,
    ):
        self.proximity_pct = proximity_pct / 100
        self.max_pullback_pct = max_pullback_pct / 100
        self.vol_mult = vol_mult

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        if df is None or len(df) < 60:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason="insufficient data")

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        volume = df["Volume"].astype(float)
        price = float(close.iloc[-1])

        # 52-week high excluding today
        week52_high = float(high.iloc[:-1].max())
        if week52_high <= 0:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="invalid 52W high")

        # Distance from 52W high
        pct_below = (week52_high - price) / week52_high

        # Check if stock recently broke out (was within 1% of 52W high in last 15 days)
        recent_high = float(high.iloc[-15:].max())
        had_breakout = (week52_high - recent_high) / week52_high < 0.01

        if not had_breakout:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason=f"no recent 52W-high touch ({pct_below*100:.1f}% below)")

        # Retest condition: currently 0-5% below 52W high
        if pct_below > self.max_pullback_pct:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason=f"pullback too deep: {pct_below*100:.1f}% > {self.max_pullback_pct*100:.0f}%")

        # Near the breakout level (within proximity_pct)
        if pct_below > self.proximity_pct:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason=f"not yet back to breakout zone ({pct_below*100:.1f}%)")

        # Volume: today should be moderate (not a panic seller's capitulation)
        vol_20d_avg = float(volume.iloc[-21:-1].mean()) or 1.0
        today_vol_ratio = float(volume.iloc[-1]) / vol_20d_avg

        # Retest entry: moderate-to-normal volume (0.5–1.5× avg means the sellers are gone)
        if today_vol_ratio > 2.5:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason=f"retest volume too high ({today_vol_ratio:.2f}×) — distribution risk")

        q_boost = (quality_score - 50) / 100
        closeness_score = (1 - pct_below / self.max_pullback_pct) * 20
        score = self._clip(68 + closeness_score + q_boost * 7)

        return PositionalSignal(
            ticker, "BUY", self.name, score, price,
            hold_days=12,
            conviction="high" if pct_below < 0.01 else "medium",
            reason=(f"52W high retest: {pct_below*100:.1f}% below "
                    f"52W-high={week52_high:.2f}, vol={today_vol_ratio:.2f}×"),
            meta={
                "week52_high": week52_high,
                "pct_below": round(pct_below * 100, 2),
                "vol_ratio": round(today_vol_ratio, 2),
            },
        )

"""
"1-2-3-4" Young Momentum Continuation Strategy — Siddharth Bhanushali style.

Designed to programmatically capture young, aggressive institutional momentum
right at its first meaningful breath or pause (unlike Minervini VCP which waits
for multiple contractions).

Rules:
1. Base Breakout: Origin point. Stock breaks out of a multi-month base on high volume.
2. Impulse Leg: Price surges vertically by 20% to 50% over a compressed window of 5–15 trading sessions.
3. Healthy Pause: Price pulls back or consolidates sideways for 2-6 days.
   - Retracement must NOT breach the 38.2% Fibonacci level of the impulse leg.
   - Volume must drop below the 20-day average volume.
4. Continuation Entry: Buy-stop order placed 0.1% above the highest point of the pause candles.
   - SL: Pegged right below the swing low of the Phase 3 consolidation.
   - Creates a highly asymmetric risk-to-reward ratio.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import (
    POS_YMC_IMPULSE_MIN,
    POS_YMC_IMPULSE_MAX,
    POS_YMC_MAX_PAUSE,
    POS_YMC_FIB_THRESHOLD,
)
from positional.strategies.base import BasePositionalStrategy, PositionalSignal

log = logging.getLogger(__name__)


class YoungMomentumStrategy(BasePositionalStrategy):
    name = "young_momentum"

    def __init__(
        self,
        min_impulse_pct: float = POS_YMC_IMPULSE_MIN,
        max_impulse_pct: float = POS_YMC_IMPULSE_MAX,
        max_pause_days: int = POS_YMC_MAX_PAUSE,
        fib_threshold: float = POS_YMC_FIB_THRESHOLD,
    ):
        self.min_impulse_pct = min_impulse_pct
        self.max_impulse_pct = max_impulse_pct
        self.max_pause_days = max_pause_days
        self.fib_threshold = fib_threshold

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        # Need at least 50 days of history for 20-day volume average and impulse lookback
        needed = 50
        if df is None or len(df) < needed:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason=f"need {needed}+ EOD daily bars (got {len(df) if df is not None else 0})")

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float)
        
        price = float(close.iloc[-1])
        n_bars = len(df)

        # ── 1. The 20-day average volume for baseline comparisons ─────────────
        vol_avg_20d = float(volume.iloc[-21:-1].mean()) or 1.0

        # ── 2. Scan for recent Impulse Leg (Phase 2) ──────────────────────────
        # We look back over the last 5 to 20 sessions for an impulse peak.
        # Let's find the absolute highest high in the last 20 sessions to define our Impulse Peak.
        # We exclude today if today is the breakout day itself, or scan lookback ranges.
        # To make it robust, we search for the highest high index in the last 15 days (excluding today).
        peak_idx = -1
        peak_high = 0.0
        
        # Pullback pause must last between 2 and 6 days (meaning the peak occurred 2 to 7 days ago)
        for i in range(2, 8):
            bar_idx = n_bars - i - 1
            if bar_idx < 0:
                continue
            h_val = float(high.iloc[bar_idx])
            if h_val > peak_high:
                peak_high = h_val
                peak_idx = bar_idx

        if peak_idx < 0 or peak_high <= 0:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="Impulse: No recent impulse peak high located")

        # Now locate the swing low (origin point of impulse leg) before the peak
        # The swing low should be 5 to 15 sessions before the peak
        swing_low = float("inf")
        low_idx = -1
        
        start_scan = max(0, peak_idx - 15)
        end_scan = max(1, peak_idx - 5)
        
        for idx in range(start_scan, end_scan + 1):
            l_val = float(low.iloc[idx])
            if l_val < swing_low:
                swing_low = l_val
                low_idx = idx

        if low_idx < 0 or swing_low <= 0:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="Impulse: No valid swing low found before the peak")

        # Calculate Impulse Leg surge ratio
        surge_pct = (peak_high - swing_low) / swing_low * 100
        
        if not (self.min_impulse_pct <= surge_pct <= self.max_impulse_pct):
            reason = f"Impulse: Surge ratio of {surge_pct:.1f}% is outside bounds [{self.min_impulse_pct}%, {self.max_impulse_pct}%]"
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price, reason=reason)

        # ── 3. The Healthy Pause (Phase 3) ───────────────────────────────────
        # The pause is defined from the bar *after* the peak to yesterday.
        pause_start_idx = peak_idx + 1
        pause_end_idx = n_bars - 2  # yesterday
        
        pause_bars_count = pause_end_idx - pause_start_idx + 1
        if pause_bars_count < 2 or pause_bars_count > self.max_pause_days:
            reason = f"Pause: Pause duration of {pause_bars_count} days is outside limits [2, {self.max_pause_days}]"
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price, reason=reason)

        # A. Fibonacci 38.2% Retracement Check
        # Retracement must not breach the 38.2% level of the impulse leg
        impulse_range = peak_high - swing_low
        fib_support = peak_high - (self.fib_threshold * impulse_range)
        
        # Verify lows of the pause candles (excluding today) do not breach support
        pause_lows = low.iloc[pause_start_idx : pause_end_idx + 1].astype(float)
        lowest_pause_low = float(pause_lows.min())
        
        if lowest_pause_low < fib_support:
            reason = (f"Pause: Retracement too deep. Lowest low {lowest_pause_low:.2f} "
                      f"breached 38.2% Fib level {fib_support:.2f} (Impulse peak={peak_high:.2f}, low={swing_low:.2f})")
            return PositionalSignal(ticker, "HOLD", self.name, 53.0, price, reason=reason)

        # B. Volume Dry-Up Check during Pause
        # Volume must be below average
        pause_vols = volume.iloc[pause_start_idx : pause_end_idx + 1].astype(float)
        pause_vol_avg = float(pause_vols.mean())
        
        if pause_vol_avg >= vol_avg_20d:
            reason = f"Pause: Average pause volume ({pause_vol_avg:.0f}) is higher than 20-day average ({vol_avg_20d:.0f}) — no dry-up"
            return PositionalSignal(ticker, "HOLD", self.name, 56.0, price, reason=reason)

        # ── 4. The Continuation Entry (Phase 4) ──────────────────────────────
        # Buy-stop trigger is 0.1% above the highest high of the pause candles
        pause_highs = high.iloc[pause_start_idx : pause_end_idx + 1].astype(float)
        max_pause_high = float(pause_highs.max())
        trigger_price = max_pause_high * 1.001
        
        # Today's close or high must clear the buy-stop trigger
        is_triggered = price >= trigger_price
        
        # Today's volume should also be expanding to confirm the momentum continuation
        today_vol_ratio = float(volume.iloc[-1]) / vol_avg_20d
        
        if not is_triggered:
            reason = f"Continuation: Awaiting trigger above pause high of {trigger_price:.2f} (Close={price:.2f})"
            return PositionalSignal(ticker, "HOLD", self.name, 59.0, price, reason=reason)

        # Risk parameters
        stop_loss = lowest_pause_low * 0.995  # Slightly below pause swing low
        risk_pct = (trigger_price - stop_loss) / trigger_price * 100
        
        # Skip if risk is excessively wide (e.g. > 8% of trade price)
        if risk_pct > 8.0:
            reason = f"Continuation: Triggered but risk-to-stop of {risk_pct:.1f}% is too wide (limit is 8.0%)"
            return PositionalSignal(ticker, "HOLD", self.name, 58.0, price, reason=reason)

        # ── SUCCESSFUL BUY SIGNAL TRIGGERED ──
        # Highly asymmetric trade!
        base_score = 74.0
        
        # Squeeze in bonus score for extremely tight consolidation (narrow pause range)
        pause_range_pct = (max_pause_high - lowest_pause_low) / max_pause_high * 100
        tightness_bonus = max(0.0, (5.0 - pause_range_pct) * 2.0)  # max +10 for tight pause
        
        # Add volume confirmation bonus
        vol_bonus = min(5.0, (today_vol_ratio - 1.0) * 1.5) if today_vol_ratio > 1.0 else 0.0
        quality_bonus = (quality_score - 50.0) / 10.0
        
        score = self._clip(base_score + tightness_bonus + vol_bonus + quality_bonus)
        
        final_reason = (
            f"1-2-3-4 Continuation Triggered: Young momentum continuation above {trigger_price:.2f}. "
            f"Impulse surge was {surge_pct:.1f}% (over {peak_idx - low_idx} days), pause held 38.2% Fib support "
            f"({fib_support:.2f}) over {pause_bars_count} days. Tight risk-to-stop: {risk_pct:.1f}% (R:R ~ 1:4)."
        )

        meta = {
            "impulse_surge_pct": round(surge_pct, 2),
            "pause_days": pause_bars_count,
            "fib_support_level": round(fib_support, 2),
            "trigger_price": round(trigger_price, 2),
            "stop_loss": round(stop_loss, 2),
            "risk_pct": round(risk_pct, 2),
            "today_vol_ratio": round(today_vol_ratio, 2)
        }

        return PositionalSignal(
            ticker=ticker,
            action="BUY",
            strategy=self.name,
            score=score,
            price=price,
            reason=final_reason,
            hold_days=10,  # Young momentum continuation is high velocity, expected exit in 10 trading days
            conviction="high" if score >= 80.0 else "medium",
            meta=meta
        )

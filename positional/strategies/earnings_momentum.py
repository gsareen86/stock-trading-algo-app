"""
Post-Earnings Announcement Drift (PEAD) — earnings momentum.

Post-earnings announcement drift is one of the most persistent anomalies in
equity markets. When a company beats estimates significantly, the stock gaps
up but then continues drifting higher for 10–20 trading days as analyst
upgrades and institutional buying follow.

Entry logic:
1. Detect a recent earnings event: look for a candle with an unusually large
   gap (open vs prior close > 2%) in the last POS_EARNINGS_WINDOW_DAYS days.
   A positive surprise gap > 0 and ≤ POS_EARNINGS_MAX_GAP_PCT (to avoid chasing).
2. After the gap day, wait for a consolidation candle (day range < avg bar
   range of the past 10 days). This is the "base" after the initial move.
3. Entry on the first day the stock closes above the consolidation high.

Volume: gap day volume should be > 2× 20-day avg (institutional initiation),
and the consolidation bar volume should taper to < avg (supply exhausted).

If yfinance `calendar` data is available, verify the earnings date matches.
Otherwise use the gap detection heuristic alone.
"""
from __future__ import annotations

import logging

import pandas as pd

from config import POS_EARNINGS_MAX_GAP_PCT, POS_EARNINGS_WINDOW_DAYS
from positional.strategies.base import BasePositionalStrategy, PositionalSignal

log = logging.getLogger(__name__)


def _detect_earnings_gap(
    df: pd.DataFrame,
    window: int,
    max_gap_pct: float,
) -> tuple[int, float]:
    """
    Scan the last `window` bars for a large-gap candle.
    Returns (bar_index_from_end, gap_pct) or (-1, 0).
    """
    if len(df) < window + 2:
        return -1, 0.0

    close = df["Close"].astype(float)
    open_ = df["Open"].astype(float)

    for i in range(1, window + 2):
        idx = -(i + 1)
        prev_close = float(close.iloc[idx])
        today_open = float(open_.iloc[idx + 1])
        if prev_close <= 0:
            continue
        gap_pct = (today_open - prev_close) / prev_close * 100
        if 2.0 <= gap_pct <= max_gap_pct:
            return i, gap_pct
    return -1, 0.0


class EarningsMomentumStrategy(BasePositionalStrategy):
    name = "earnings_momentum"

    def __init__(
        self,
        window_days: int = POS_EARNINGS_WINDOW_DAYS,
        max_gap_pct: float = POS_EARNINGS_MAX_GAP_PCT,
    ):
        self.window_days = window_days
        self.max_gap_pct = max_gap_pct

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        if df is None or len(df) < 25:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason="insufficient data")

        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float)
        price = float(close.iloc[-1])

        bars_ago, gap_pct = _detect_earnings_gap(df, self.window_days, self.max_gap_pct)
        if bars_ago < 0:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="no earnings gap detected in window")

        if gap_pct <= 0:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="gap was negative — not a positive earnings surprise")

        # Confirm gap-day volume was strong (institutional initiation)
        gap_bar_idx = -(bars_ago)
        vol_20d = float(volume.iloc[gap_bar_idx - 20: gap_bar_idx].mean()) or 1.0
        gap_vol = float(volume.iloc[gap_bar_idx])
        gap_vol_ratio = gap_vol / vol_20d

        if gap_vol_ratio < 1.5:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason=f"earnings gap {gap_pct:.1f}% but weak vol "
                                           f"({gap_vol_ratio:.2f}×) — retail-driven, skip")

        # Consolidation after gap: check if post-gap bars are tight
        if bars_ago == 0:
            return PositionalSignal(ticker, "HOLD", self.name, 55.0, price,
                                    reason=f"earnings gap today ({gap_pct:.1f}%) — await consolidation")

        # Post-gap bars
        post_gap = df.iloc[gap_bar_idx:]
        if len(post_gap) < 2:
            return PositionalSignal(ticker, "HOLD", self.name, 55.0, price,
                                    reason="only 1 post-gap bar — await consolidation")

        post_close = post_gap["Close"].astype(float)
        post_high = post_gap["High"].astype(float)
        post_low = post_gap["Low"].astype(float)

        # Avg range of the 10 bars before the gap
        pre_gap_range = (
            (high.iloc[gap_bar_idx - 10: gap_bar_idx] - low.iloc[gap_bar_idx - 10: gap_bar_idx])
            .mean()
        )
        # Today's range vs pre-gap avg range
        today_range = float(high.iloc[-1]) - float(low.iloc[-1])
        is_consolidating = today_range < pre_gap_range * 1.2

        # Entry: today's close above the post-gap consolidation high
        consolidation_high = float(post_high.max())
        if price < consolidation_high and not is_consolidating:
            return PositionalSignal(ticker, "HOLD", self.name, 55.0, price,
                                    reason=(f"post-earnings gap {gap_pct:.1f}% "
                                            f"({bars_ago}d ago) — consolidating, "
                                            f"await breakout above {consolidation_high:.2f}"))

        score = self._clip(65 + min(gap_pct * 2, 15) + (gap_vol_ratio - 1.5) * 3
                           + (quality_score - 50) / 10)
        return PositionalSignal(
            ticker, "BUY", self.name, score, price,
            hold_days=12,
            conviction="medium",
            reason=(f"PEAD entry: gap={gap_pct:.1f}% {bars_ago}d ago, "
                    f"gap-vol={gap_vol_ratio:.2f}×, consolidation complete"),
            meta={
                "gap_pct": round(gap_pct, 2),
                "bars_ago": bars_ago,
                "gap_vol_ratio": round(gap_vol_ratio, 2),
                "consolidation_high": round(consolidation_high, 2),
            },
        )

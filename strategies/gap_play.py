"""
Gap-and-go / Gap-fade strategy — first-30-min directional edge.

At 09:15 IST every NSE stock prints its first candle of the day. The gap
(today's open vs yesterday's close) is one of the highest-edge intraday
signals in Indian equities. Two regimes:

1. **Gap-and-go (continuation)**: |gap| > GAP_GO_PCT AND first-bar volume
   ratio >= GAP_GO_VOL_MULT × the prior session's average bar-volume.
   Strong volume on the gap == institutional initiation; the gap usually
   extends. → BUY on up-gap, SELL on down-gap.

2. **Gap-fade (reversion)**: |gap| > GAP_FADE_PCT but volume is weak (<
   1.0× prior avg). Retail-driven gaps without institutional follow-through
   tend to fill. → SELL on up-gap, BUY on down-gap.

The strategy only fires inside ``GAP_ENTRY_WINDOW_MIN`` minutes of open;
after that the edge decays to noise.
"""
from __future__ import annotations

from datetime import time

import pandas as pd

from config import (
    GAP_ENTRY_WINDOW_MIN,
    GAP_FADE_PCT,
    GAP_GO_PCT,
    GAP_GO_VOL_MULT,
)
from strategies.base import BaseStrategy, Signal


_MARKET_OPEN = time(9, 15)


def _today_session_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    latest_date = df.index[-1].date()
    return df[df.index.map(lambda t: t.date() == latest_date)]


def _prior_session_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    latest_date = df.index[-1].date()
    prior = df[df.index.map(lambda t: t.date() < latest_date)]
    if prior.empty:
        return prior
    last_prior_date = prior.index[-1].date()
    return prior[prior.index.map(lambda t: t.date() == last_prior_date)]


def _bar_minutes_since_open(ts) -> int:
    t = ts.time() if hasattr(ts, "time") else ts
    open_min = _MARKET_OPEN.hour * 60 + _MARKET_OPEN.minute
    cur_min = t.hour * 60 + t.minute
    return cur_min - open_min


class GapPlayStrategy(BaseStrategy):
    name = "gap_play"

    def __init__(self,
                 gap_go_pct: float = GAP_GO_PCT,
                 gap_fade_pct: float = GAP_FADE_PCT,
                 gap_go_vol_mult: float = GAP_GO_VOL_MULT,
                 entry_window_min: int = GAP_ENTRY_WINDOW_MIN):
        self.gap_go_pct = gap_go_pct
        self.gap_fade_pct = gap_fade_pct
        self.gap_go_vol_mult = gap_go_vol_mult
        self.entry_window_min = entry_window_min

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        if df is None or df.empty:
            return Signal(ticker, "HOLD", self.name, 50.0, reason="no data")

        today = _today_session_bars(df)
        prior = _prior_session_bars(df)
        if today.empty or prior.empty:
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason="need today + prior session bars")

        latest = today.iloc[-1]
        price = float(latest["Close"])

        # Only fire within the first ``entry_window_min`` of the session.
        mins_since_open = _bar_minutes_since_open(today.index[-1])
        if mins_since_open > self.entry_window_min:
            return Signal(ticker, "HOLD", self.name, 50.0, price,
                          reason=f"past gap entry window ({mins_since_open}m)")

        prior_close = float(prior["Close"].iloc[-1])
        today_open = float(today["Open"].iloc[0])
        if prior_close <= 0:
            return Signal(ticker, "HOLD", self.name, 50.0, price,
                          reason="invalid prior close")

        gap_pct = (today_open - prior_close) / prior_close * 100

        # Volume context: first bar of today vs avg prior session bar volume.
        first_bar_vol = float(today["Volume"].iloc[0])
        prior_avg_vol = float(prior["Volume"].mean()) or 1.0
        vol_ratio = first_bar_vol / prior_avg_vol

        # ----- Gap-and-go (continuation) -----
        if abs(gap_pct) >= self.gap_go_pct and vol_ratio >= self.gap_go_vol_mult:
            score = self._clip(65 + min(abs(gap_pct) * 4, 20)
                               + min(vol_ratio * 2, 10))
            if gap_pct > 0:
                return Signal(
                    ticker, "BUY", self.name, score, price,
                    reason=(f"Gap-and-go LONG: +{gap_pct:.2f}% gap on "
                            f"{vol_ratio:.2f}× volume"),
                    meta={"gap_pct": gap_pct, "vol_ratio": vol_ratio,
                          "mode": "go"},
                )
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=(f"Gap-and-go SHORT: {gap_pct:.2f}% gap on "
                        f"{vol_ratio:.2f}× volume"),
                meta={"gap_pct": gap_pct, "vol_ratio": vol_ratio,
                      "mode": "go"},
            )

        # ----- Gap-fade (reversion) -----
        if abs(gap_pct) >= self.gap_fade_pct and vol_ratio < 1.0:
            score = self._clip(60 + min(abs(gap_pct) * 3, 20))
            if gap_pct > 0:
                # Up-gap with weak volume → fade short back to prior close.
                return Signal(
                    ticker, "SELL", self.name, score, price,
                    reason=(f"Gap-fade SHORT: +{gap_pct:.2f}% gap, "
                            f"weak vol {vol_ratio:.2f}×"),
                    meta={"gap_pct": gap_pct, "vol_ratio": vol_ratio,
                          "mode": "fade"},
                )
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=(f"Gap-fade LONG: {gap_pct:.2f}% gap, "
                        f"weak vol {vol_ratio:.2f}×"),
                meta={"gap_pct": gap_pct, "vol_ratio": vol_ratio,
                      "mode": "fade"},
            )

        return Signal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=(f"gap {gap_pct:+.2f}% / vol {vol_ratio:.2f}× "
                    "— no qualifying setup"),
            meta={"gap_pct": gap_pct, "vol_ratio": vol_ratio},
        )

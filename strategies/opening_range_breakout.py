"""
Opening Range Breakout (ORB) — direction-agnostic intraday breakout strategy.

Concept
-------
Define the "opening range" as the price extremes during the first ``window_min``
minutes of NSE trading (default 09:15-09:30 IST). After the range closes:
  * BUY  if a 15-min candle closes ABOVE the range high.
  * SELL if a 15-min candle closes BELOW the range low.
  * Initial stop is the opposite extreme of the range.

Why this lives well alongside the existing strategies
-----------------------------------------------------
The existing momentum / EMA-crossover stack is structurally long-biased — on
red days nearly every BUY signal is gated out by the regime filter and almost
no SELL signals fire, so the bot sits flat. ORB by construction emits LONGs
and SHORTs with equal frequency, which restores participation in either
direction.

Score: scaled by breakout magnitude relative to the range width, capped at 90.
References: Toby Crabel's *Day Trading with Short Term Price Patterns* (1990),
the original ORB literature.
"""
from __future__ import annotations

from datetime import time

import pandas as pd

from config import ORB_MIN_BREAKOUT_PCT, ORB_WINDOW_MIN
from strategies.base import BaseStrategy, Signal


# Market open in IST. We compare timestamps in their original tz (yfinance
# returns India-local timestamps for ``.NS`` tickers) and fall back to a
# tz-naive comparison if the index is naive.
_MARKET_OPEN = time(9, 15)


def _to_ist_time(ts) -> time:
    """Best-effort conversion of a pandas timestamp to an IST time-of-day."""
    try:
        if getattr(ts, "tzinfo", None) is not None:
            # yfinance '.NS' candles are typically tz-aware in IST already.
            return ts.time()
        return ts.time()
    except Exception:
        return time(0, 0)


def _today_session_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Slice df to bars with the same calendar date as the latest bar."""
    if df.empty:
        return df
    latest_date = df.index[-1].date()
    return df[df.index.map(lambda t: t.date() == latest_date)]


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Breakout above/below the first ``window_min`` minutes of the session."""

    name = "orb"

    def __init__(self, window_min: int = ORB_WINDOW_MIN,
                 min_breakout_pct: float = ORB_MIN_BREAKOUT_PCT):
        self.window_min = window_min
        self.min_breakout_pct = min_breakout_pct

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        if df is None or df.empty:
            return Signal(ticker, "HOLD", self.name, 50.0, reason="no data")

        today = _today_session_bars(df)
        if len(today) < 2:
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason="not enough intraday bars yet")

        # Define the opening-range window: [09:15, 09:15 + window_min) IST.
        end_minutes = _MARKET_OPEN.hour * 60 + _MARKET_OPEN.minute + self.window_min
        end_t = time(end_minutes // 60, end_minutes % 60)

        opening = today[today.index.map(lambda t: _to_ist_time(t) < end_t)]
        post = today[today.index.map(lambda t: _to_ist_time(t) >= end_t)]

        price = float(today["Close"].iloc[-1])

        if opening.empty:
            return Signal(ticker, "HOLD", self.name, 50.0, price,
                          reason="opening range not yet formed")
        if post.empty:
            # Still inside the opening range — no decision yet.
            return Signal(ticker, "HOLD", self.name, 50.0, price,
                          reason=f"inside opening range ({self.window_min}m)")

        or_high = float(opening["High"].max())
        or_low = float(opening["Low"].min())
        or_width = or_high - or_low
        if or_width <= 0:
            return Signal(ticker, "HOLD", self.name, 50.0, price,
                          reason="opening range has zero width")

        # The most recent post-range bar's close decides direction.
        last_close = float(post["Close"].iloc[-1])
        breakout_up = (last_close - or_high) / or_high * 100
        breakout_dn = (or_low - last_close) / or_low * 100

        if last_close > or_high and breakout_up >= self.min_breakout_pct:
            # Score scales with breakout strength relative to range width.
            mag = (last_close - or_high) / or_width
            score = self._clip(60 + min(mag * 30, 30))
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=(f"ORB long: close {last_close:.2f} > OR-high {or_high:.2f} "
                        f"(+{breakout_up:.2f}%)"),
                meta={"or_high": or_high, "or_low": or_low,
                      "or_width": or_width, "breakout_pct": breakout_up},
            )
        if last_close < or_low and breakout_dn >= self.min_breakout_pct:
            mag = (or_low - last_close) / or_width
            score = self._clip(60 + min(mag * 30, 30))
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=(f"ORB short: close {last_close:.2f} < OR-low {or_low:.2f} "
                        f"(-{breakout_dn:.2f}%)"),
                meta={"or_high": or_high, "or_low": or_low,
                      "or_width": or_width, "breakout_pct": breakout_dn},
            )

        return Signal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=(f"inside OR band [{or_low:.2f}, {or_high:.2f}]; "
                    f"price {last_close:.2f}"),
            meta={"or_high": or_high, "or_low": or_low},
        )

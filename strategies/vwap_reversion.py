"""
VWAP mean-reversion strategy — direction-agnostic.

Concept
-------
VWAP (Volume-Weighted Average Price) is the canonical intraday "fair value"
reference for institutional traders. Price spends most of the day within ~1
ATR of VWAP and tends to revert to it from extremes.

Logic
-----
Compute VWAP from the start of the current trading day. Look at where the
last few bars sit relative to VWAP:
  * BUY  if price is significantly BELOW VWAP and the most recent bar is a
    bullish reversal (close > previous close, close > open).
  * SELL if price is significantly ABOVE VWAP and the most recent bar is a
    bearish reversal (close < previous close, close < open).

The "significant" threshold scales with intraday volatility (recent stdev of
returns), so the band auto-tightens on quiet days and widens on noisy ones.

Score scales with distance from VWAP relative to that volatility band.

Why it complements the existing stack
-------------------------------------
On rangebound days the trend strategies (EMA cross, momentum) emit nothing or
chop themselves out. VWAP mean-reversion fires constantly on those days —
two-way, since it triggers on both above-VWAP rallies and below-VWAP dips.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import VWAP_BAND_K, VWAP_VOL_LOOKBACK
from strategies.base import BaseStrategy, Signal


def _today_session_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    latest_date = df.index[-1].date()
    return df[df.index.map(lambda t: t.date() == latest_date)]


def _session_vwap(df_today: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP from the first bar of the session."""
    typ = (df_today["High"] + df_today["Low"] + df_today["Close"]) / 3.0
    pv = typ * df_today["Volume"]
    return pv.cumsum() / df_today["Volume"].cumsum().replace(0, np.nan)


class VWAPReversionStrategy(BaseStrategy):
    """Fade price away from the session VWAP when an intrabar reversal prints."""

    name = "vwap_reversion"

    def __init__(self, band_k: float = VWAP_BAND_K,
                 vol_lookback: int = VWAP_VOL_LOOKBACK):
        self.band_k = band_k
        self.vol_lookback = vol_lookback

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        if df is None or df.empty:
            return Signal(ticker, "HOLD", self.name, 50.0, reason="no data")

        today = _today_session_bars(df)
        if len(today) < max(self.vol_lookback + 2, 4):
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason="insufficient intraday bars for VWAP band")

        vwap = _session_vwap(today)
        ret = today["Close"].pct_change().dropna()
        # Recent intrabar volatility — used to size the reversion band.
        vol = float(ret.tail(self.vol_lookback).std()) if not ret.empty else 0.0

        last = today.iloc[-1]
        prev = today.iloc[-2]
        price = float(last["Close"])
        vwap_now = float(vwap.iloc[-1])
        if not np.isfinite(vwap_now) or vwap_now <= 0:
            return Signal(ticker, "HOLD", self.name, 50.0, price,
                          reason="vwap undefined")

        dist_pct = (price - vwap_now) / vwap_now
        # Band scales with realised intraday vol, floor at 0.3% so we don't
        # trade noise on dead-quiet days.
        band = max(self.band_k * vol, 0.003)

        bullish_bar = price > float(prev["Close"]) and price > float(last["Open"])
        bearish_bar = price < float(prev["Close"]) and price < float(last["Open"])

        # BUY: price stretched BELOW VWAP and reversing back up.
        if dist_pct <= -band and bullish_bar:
            stretch = abs(dist_pct) / band
            score = self._clip(60 + min(stretch * 20, 30))
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=(f"VWAP-revert long: price {price:.2f} {dist_pct*100:+.2f}% "
                        f"vs VWAP {vwap_now:.2f}, band ±{band*100:.2f}%"),
                meta={"vwap": vwap_now, "dist_pct": dist_pct, "band": band},
            )
        # SELL: price stretched ABOVE VWAP and reversing back down.
        if dist_pct >= band and bearish_bar:
            stretch = dist_pct / band
            score = self._clip(60 + min(stretch * 20, 30))
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=(f"VWAP-revert short: price {price:.2f} {dist_pct*100:+.2f}% "
                        f"vs VWAP {vwap_now:.2f}, band ±{band*100:.2f}%"),
                meta={"vwap": vwap_now, "dist_pct": dist_pct, "band": band},
            )

        return Signal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=(f"price {price:.2f} within VWAP band "
                    f"({dist_pct*100:+.2f}% / ±{band*100:.2f}%)"),
            meta={"vwap": vwap_now, "dist_pct": dist_pct},
        )

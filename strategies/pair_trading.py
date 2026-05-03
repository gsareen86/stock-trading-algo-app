"""
Pair trading (statistical arbitrage) — direction-agnostic.

For correlated NIFTY pairs (HDFCBANK/ICICIBANK, RELIANCE/ONGC, TCS/INFY,
etc.) the price ratio is mean-reverting. When |z-score| of the ratio
exceeds an entry threshold we go LONG the underperformer and SHORT the
outperformer; we close when the z-score reverts to ~0.

This strategy violates the strict "single ticker" interface of the other
strategies because it needs the partner ticker's series too. We resolve
this by:
  * Reading the partner from ``PAIR_TRADING_PAIRS`` in config.
  * Fetching the partner's candles from the disk cache via the same
    ``data.fetcher.fetch_candles`` call the runner uses. Both legs of the
    cycle's universe will already be cached after ``fetch_batch``.
  * Emitting only ONE signal per call — for the ticker passed in. Each
    pair therefore generates two evaluations per cycle (one for each side),
    and the composite scorer ends up with one BUY + one SELL — perfect
    for direction-balanced exposure.

Score scales with |z|; max-out at z=3. Below entry threshold → HOLD.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    PAIR_TRADING_PAIRS,
    PAIR_Z_ENTRY,
    PAIR_Z_LOOKBACK,
)
from strategies.base import BaseStrategy, Signal

log = logging.getLogger(__name__)


def _build_partner_index() -> dict[str, str]:
    """Flatten ``PAIR_TRADING_PAIRS`` into a ticker→partner dict.

    Each pair (A, B) inserts BOTH A→B and B→A so a single config entry covers
    both legs.
    """
    index: dict[str, str] = {}
    for a, b in PAIR_TRADING_PAIRS:
        index[a] = b
        index[b] = a
    return index


_PARTNER_INDEX = _build_partner_index()


def _load_partner_df(partner: str) -> Optional[pd.DataFrame]:
    """Fetch the partner's candle df (cache-first)."""
    try:
        from data.fetcher import fetch_candles
    except Exception as e:
        log.debug("pair_trading: fetcher import failed: %s", e)
        return None
    try:
        df = fetch_candles(partner)
        return df if df is not None and not df.empty else None
    except Exception as e:
        log.debug("pair_trading: partner fetch failed for %s: %s", partner, e)
        return None


class PairTradingStrategy(BaseStrategy):
    """Z-score based mean-reversion on the price ratio of a configured pair."""

    name = "pair_trading"

    def __init__(self, z_entry: float = PAIR_Z_ENTRY,
                 lookback: int = PAIR_Z_LOOKBACK):
        self.z_entry = z_entry
        self.lookback = lookback

    def generate(self, ticker: str, df: pd.DataFrame) -> Signal:
        partner = _PARTNER_INDEX.get(ticker)
        if partner is None:
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason="ticker has no configured pair partner")

        if df is None or len(df) < self.lookback + 5:
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason="insufficient data for pair z-score")

        partner_df = _load_partner_df(partner)
        if partner_df is None or len(partner_df) < self.lookback + 5:
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason=f"partner {partner} unavailable")

        # Align the two series on their shared timestamps.
        a = df["Close"].astype(float)
        b = partner_df["Close"].astype(float)
        joined = pd.concat([a, b], axis=1, join="inner").dropna()
        if len(joined) < self.lookback + 5:
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason=f"only {len(joined)} aligned bars with {partner}")

        joined.columns = ["a", "b"]
        ratio = joined["a"] / joined["b"]
        window = ratio.tail(self.lookback)
        mu = float(window.mean())
        sd = float(window.std())
        if sd <= 0 or not np.isfinite(sd):
            return Signal(ticker, "HOLD", self.name, 50.0,
                          reason="pair ratio std is zero / non-finite")

        z = (float(ratio.iloc[-1]) - mu) / sd
        price = float(joined["a"].iloc[-1])

        # When z is HIGH the ratio (a/b) is stretched up → ``a`` outperformed
        # ``b``: SHORT a, LONG b. We emit only the side for ``ticker``.
        if z >= self.z_entry:
            score = self._clip(60 + min(abs(z) * 8, 30))
            return Signal(
                ticker, "SELL", self.name, score, price,
                reason=(f"Pair short: {ticker}/{partner} z={z:+.2f} "
                        f"≥ {self.z_entry:.2f} (ratio {ratio.iloc[-1]:.4f}, "
                        f"μ {mu:.4f}, σ {sd:.4f})"),
                meta={"partner": partner, "z": z, "ratio": float(ratio.iloc[-1])},
            )
        if z <= -self.z_entry:
            score = self._clip(60 + min(abs(z) * 8, 30))
            return Signal(
                ticker, "BUY", self.name, score, price,
                reason=(f"Pair long: {ticker}/{partner} z={z:+.2f} "
                        f"≤ -{self.z_entry:.2f}"),
                meta={"partner": partner, "z": z, "ratio": float(ratio.iloc[-1])},
            )

        return Signal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=f"pair {ticker}/{partner} z={z:+.2f} within band",
            meta={"partner": partner, "z": z},
        )

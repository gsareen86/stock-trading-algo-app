"""
Sector Rotation strategy.

Capital rotates across NSE sectors in 3–6 week cycles. The top-performing
sectors by 20-day return tend to remain in favour for the next 4 weeks.

Logic:
1. Fetch 20-day returns for 8 NSE sector indices via yfinance (cached).
2. Rank sectors. Top-N are "in rotation".
3. Map the ticker's sector to the nearest index (via fundamentals table).
4. BUY if sector is in the top-N AND ticker's own momentum is positive.
5. SELL if the sector has flipped into the bottom half (distribution phase).

Score bonus for catching-up tickers: ticker ranked 4th–8th best within the
in-rotation sector over the same 20-day window has the best forward expected
return (not yet extended, but the sector wind is at its back).
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from config import (
    POS_SECTOR_LOOKBACK,
    POS_SECTOR_TOP_N,
    SECTOR_INDEX_TICKERS,
    POSITIONAL_CANDLE_INTERVAL,
)
from positional.strategies.base import BasePositionalStrategy, PositionalSignal

log = logging.getLogger(__name__)

# Mapping from yfinance sector strings → our index keys
_SECTOR_MAP: Dict[str, str] = {
    "technology":                "IT",
    "information technology":    "IT",
    "consumer technology":       "IT",
    "financial services":        "Bank",
    "financial":                 "Bank",
    "banks":                     "Bank",
    "consumer defensive":        "FMCG",
    "consumer staples":          "FMCG",
    "healthcare":                "Pharma",
    "consumer cyclical":         "Auto",
    "basic materials":           "Metal",
    "energy":                    "Energy",
    "real estate":               "Realty",
}

_sector_rank_cache: Dict[str, float] = {}   # sector_key → 20d return %
_cache_ts: Optional[str] = None


def _fetch_sector_returns(lookback: int = POS_SECTOR_LOOKBACK) -> Dict[str, float]:
    """Fetch 20-day returns for sector indices. Returns dict {sector_key: return_pct}."""
    global _sector_rank_cache, _cache_ts
    from datetime import datetime
    from config import IST
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _cache_ts == today and _sector_rank_cache:
        return _sector_rank_cache

    returns: Dict[str, float] = {}
    try:
        from data.fetcher import fetch_candles
        for sector_key, yticker in SECTOR_INDEX_TICKERS.items():
            try:
                df = fetch_candles(yticker, interval="1d", days=lookback + 5)
                if df is None or len(df) < lookback + 1:
                    continue
                close = df["Close"].astype(float)
                ret = (float(close.iloc[-1]) - float(close.iloc[-lookback])) / float(close.iloc[-lookback]) * 100
                returns[sector_key] = ret
            except Exception as e:
                log.debug("sector %s fetch failed: %s", sector_key, e)
    except Exception as e:
        log.warning("sector_rotation: fetcher unavailable: %s", e)

    if returns:
        _sector_rank_cache = returns
        _cache_ts = today
    return returns


def _ticker_sector(ticker: str) -> Optional[str]:
    """Look up the ticker's sector from the fundamentals DB table."""
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT sector FROM fundamentals WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row and row["sector"]:
            return row["sector"].lower()
    except Exception:
        pass
    return None


class SectorRotationStrategy(BasePositionalStrategy):
    name = "sector_rotation"

    def __init__(
        self,
        lookback: int = POS_SECTOR_LOOKBACK,
        top_n: int = POS_SECTOR_TOP_N,
    ):
        self.lookback = lookback
        self.top_n = top_n

    def generate(
        self,
        ticker: str,
        df: pd.DataFrame,
        quality_score: float = 50.0,
    ) -> PositionalSignal:
        if df is None or len(df) < self.lookback + 5:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0,
                                    reason="insufficient data")

        close = df["Close"].astype(float)
        price = float(close.iloc[-1])

        # Determine ticker's sector
        raw_sector = _ticker_sector(ticker)
        sector_key = None
        if raw_sector:
            for k, v in _SECTOR_MAP.items():
                if k in raw_sector:
                    sector_key = v
                    break

        if sector_key is None:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="sector unknown — cannot rank")

        # Sector returns
        sector_returns = _fetch_sector_returns(self.lookback)
        if not sector_returns:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason="sector index data unavailable")

        if sector_key not in sector_returns:
            return PositionalSignal(ticker, "HOLD", self.name, 50.0, price,
                                    reason=f"no return data for sector {sector_key}")

        # Rank sectors
        ranked = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
        sector_rank = next((i + 1 for i, (k, _) in enumerate(ranked) if k == sector_key), 99)
        sector_ret = sector_returns[sector_key]

        in_rotation = sector_rank <= self.top_n
        in_distribution = sector_rank > len(ranked) - 2  # bottom 2

        # Ticker's own 20-day momentum
        price_20d = float(close.iloc[-self.lookback - 1]) if len(close) > self.lookback + 1 else 0
        ticker_ret = (price - price_20d) / (price_20d + 1e-10) * 100 if price_20d > 0 else 0

        if in_rotation and ticker_ret > 0:
            # "Catching up": ticker underperformed sector so far → best entry
            catching_up_bonus = max(0, (sector_ret - ticker_ret) / (abs(sector_ret) + 1))
            score = self._clip(63 + catching_up_bonus * 10 + (quality_score - 50) / 10)
            return PositionalSignal(
                ticker, "BUY", self.name, score, price,
                hold_days=20,
                conviction="medium",
                reason=(f"Sector {sector_key} rank #{sector_rank}/{len(ranked)} "
                        f"(+{sector_ret:.1f}%), ticker {ticker_ret:+.1f}% — catching up"),
                meta={"sector": sector_key, "sector_rank": sector_rank,
                      "sector_ret_20d": round(sector_ret, 2),
                      "ticker_ret_20d": round(ticker_ret, 2)},
            )

        if in_distribution and ticker_ret < 0:
            score = self._clip(62 + abs(ticker_ret) / 2)
            return PositionalSignal(
                ticker, "SELL", self.name, score, price,
                hold_days=10,
                conviction="low",
                reason=(f"Sector {sector_key} rank #{sector_rank}/{len(ranked)} "
                        f"({sector_ret:.1f}%) — distribution phase"),
                meta={"sector": sector_key, "sector_rank": sector_rank,
                      "sector_ret_20d": round(sector_ret, 2)},
            )

        return PositionalSignal(
            ticker, "HOLD", self.name, 50.0, price,
            reason=(f"Sector {sector_key} rank #{sector_rank}/{len(ranked)} "
                    f"({sector_ret:+.1f}%) — not in rotation"),
        )

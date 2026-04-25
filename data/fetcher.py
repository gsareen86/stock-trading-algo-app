"""
Market data fetcher — wraps yfinance with simple disk caching.
Single source of truth for candle data.
"""
from __future__ import annotations

import logging
import pickle
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import yfinance as yf

from config import CACHE_DIR, CANDLE_INTERVAL, LOOKBACK_DAYS
from data.universe import to_yf_ticker

log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 10 * 60,      # refresh intraday cache every 10 min
    "30m": 20 * 60,
    "60m": 30 * 60,
    "1h": 30 * 60,
    "1d": 60 * 60 * 6,
}


def _cache_path(ticker: str, interval: str) -> Path:
    return Path(CACHE_DIR) / f"{ticker.replace('.', '_')}_{interval}.pkl"


def _is_fresh(path: Path, ttl: int) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < ttl


def fetch_candles(
    ticker: str,
    interval: str = CANDLE_INTERVAL,
    days: int = LOOKBACK_DAYS,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles for a single ticker. Returns a DataFrame with columns:
    Open, High, Low, Close, Volume, indexed by timezone-aware datetime.
    """
    yf_t = to_yf_ticker(ticker) if not ticker.endswith((".NS", ".BO")) else ticker
    path = _cache_path(yf_t, interval)
    ttl = CACHE_TTL_SECONDS.get(interval, 600)

    if use_cache and _is_fresh(path, ttl):
        try:
            return pickle.loads(path.read_bytes())
        except Exception:
            pass  # cache corrupted; refetch

    period = f"{days}d" if interval != "1d" else f"{max(days, 365)}d"
    try:
        df = yf.download(
            yf_t,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=False,
        )
    except Exception as e:
        log.warning("yfinance error for %s: %s", yf_t, e)
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # yfinance sometimes returns MultiIndex columns for single ticker — flatten.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.dropna(inplace=True)

    try:
        path.write_bytes(pickle.dumps(df))
    except Exception as e:
        log.debug("cache write failed: %s", e)

    return df


def fetch_batch(
    tickers: list[str],
    interval: str = CANDLE_INTERVAL,
    days: int = LOOKBACK_DAYS,
    use_cache: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Fetch candles for multiple tickers. Returns dict keyed by original ticker symbol."""
    out: Dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = fetch_candles(t, interval, days, use_cache=use_cache)
        if not df.empty:
            out[t] = df
    return out


def latest_price(ticker: str) -> Optional[float]:
    """Cheapest way to get a last-known price — uses the daily cache if possible."""
    df = fetch_candles(ticker, interval="1d", days=5, use_cache=True)
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])


def market_is_open(now: Optional[datetime] = None) -> bool:
    """Rough check: is NSE open right now? (IST, Mon-Fri, 9:15-15:30)."""
    now = now or datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    if now.weekday() >= 5:
        return False
    hhmm = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= hhmm <= 15 * 60 + 30


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = fetch_candles("RELIANCE", "15m", 5)
    print(df.tail())
    print(f"Rows: {len(df)}")

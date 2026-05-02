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


# How many concurrent yfinance requests to fire. yfinance is wrapping
# query2.finance.yahoo.com which tolerates ~10-15 concurrent reqs per IP
# before throttling; 8 leaves headroom for the rest of the cycle (news
# scrape, sentiment) and is the sweet spot we measured. The cache-fast
# path is lock-free so fewer threads doesn't help once the cache is warm.
FETCH_BATCH_WORKERS = 8


def fetch_batch(
    tickers: list[str],
    interval: str = CANDLE_INTERVAL,
    days: int = LOOKBACK_DAYS,
    use_cache: bool = True,
    max_workers: int = FETCH_BATCH_WORKERS,
) -> Dict[str, pd.DataFrame]:
    """Fetch candles for multiple tickers in parallel.

    The previous serial implementation was the single biggest contributor
    to cycle latency: at ~1.0-1.5s per ticker on a warm-cache miss, 50
    tickers ate 60-80 s. Parallelising with a small thread pool drops that
    to ~10 s for 50 and makes 500-ticker cycles feasible.

    Returns dict keyed by original ticker symbol; tickers that error out
    or return empty are silently dropped (caller already handles missing
    keys).
    """
    if not tickers:
        return {}

    # Single-threaded fallback for tiny batches — thread setup overhead
    # outweighs the win below ~5 tickers.
    if len(tickers) < 5 or max_workers <= 1:
        out: Dict[str, pd.DataFrame] = {}
        for t in tickers:
            df = fetch_candles(t, interval, days, use_cache=use_cache)
            if not df.empty:
                out[t] = df
        return out

    # Parallel path. We import here so module import stays light.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: Dict[str, pd.DataFrame] = {}
    workers = min(max_workers, len(tickers))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fetch") as ex:
        future_to_ticker = {
            ex.submit(fetch_candles, t, interval, days, use_cache): t
            for t in tickers
        }
        for fut in as_completed(future_to_ticker):
            t = future_to_ticker[fut]
            try:
                df = fut.result()
            except Exception as e:
                log.debug("fetch_batch worker failed for %s: %s", t, e)
                continue
            if df is not None and not df.empty:
                out[t] = df
    return out


def latest_price_with_ts(
    ticker: str,
    *,
    use_cache: bool = True,
) -> tuple[Optional[float], Optional[datetime]]:
    """Return ``(price, timestamp)`` for the ticker.

    During NSE market hours we prefer an INTRADAY interval (5m candles) so
    the price reflects what's happening right now. Outside market hours we
    fall back to daily candles — yesterday's close is the most-recent
    "real" trade price when the market is closed.

    The previous implementation used ``interval="1d"`` with a 6-HOUR cache
    TTL — fine for end-of-day P&L but it meant the dashboard's "Current"
    price was effectively yesterday's close while the market was open,
    making Unrealized P&L look frozen for hours.

    The returned timestamp is the candle timestamp from yfinance (already
    timezone-aware in most cases), letting the dashboard render a
    "Price as of …" column so the user can see exactly how stale each
    price is.
    """
    if market_is_open():
        # 5-minute candles refresh every ~5 min anyway (CACHE_TTL_SECONDS["5m"]
        # == 300s); plenty fresh for paper-trading P&L. We DON'T pass a
        # tighter TTL here because the cache TTL already matches the candle
        # cadence — refetching faster than that just yields the same row.
        df = fetch_candles(ticker, interval="5m", days=2, use_cache=use_cache)
        if not df.empty:
            try:
                ts = df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1]
            except Exception:
                ts = None
            return float(df["Close"].iloc[-1]), ts

    df = fetch_candles(ticker, interval="1d", days=5, use_cache=use_cache)
    if df.empty:
        return None, None
    try:
        ts = df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1]
    except Exception:
        ts = None
    return float(df["Close"].iloc[-1]), ts


def latest_price(ticker: str) -> Optional[float]:
    """Backwards-compatible scalar wrapper around :func:`latest_price_with_ts`."""
    price, _ = latest_price_with_ts(ticker)
    return price


# NSE trading holidays — published yearly by NSE on
# https://www.nseindia.com/resources/exchange-communication-holidays
# Update this list each January when the next year's calendar is released.
# Format: ISO date strings 'YYYY-MM-DD'. Includes weekly off via weekday()
# check; this list is for full-day holidays and full-day muhurat-only days.
NSE_HOLIDAYS: set[str] = {
    # 2026 (verified against NSE calendar; double-check before live trading)
    "2026-01-26",  # Republic Day
    "2026-02-19",  # Mahashivratri
    "2026-03-03",  # Holi
    "2026-03-20",  # Eid-Ul-Fitr (Ramzan Id)
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2026-04-21",  # Ram Navami
    "2026-04-30",  # Mahavir Jayanti  ← user reported "market closed today"
    "2026-05-01",  # Maharashtra Day
    "2026-05-27",  # Buddha Pournima
    "2026-08-15",  # Independence Day
    "2026-08-27",  # Ganesh Chaturthi
    "2026-10-02",  # Mahatma Gandhi Jayanti / Dussehra
    "2026-11-09",  # Diwali Laxmi Pujan (special trading session — block here too)
    "2026-11-10",  # Diwali Balipratipada
    "2026-11-25",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
}


def is_nse_holiday(now: Optional[datetime] = None) -> bool:
    """True if today is a known NSE full-day holiday (per NSE_HOLIDAYS)."""
    now = now or datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    return now.strftime("%Y-%m-%d") in NSE_HOLIDAYS


def market_is_open(now: Optional[datetime] = None) -> bool:
    """Is NSE open right now? Mon-Fri, 09:15-15:30 IST, AND not a holiday.

    Previously the check was just weekday + time-of-day — which marked
    holidays like Mahavir Jayanti as "open" on weekdays. The added
    NSE_HOLIDAYS set fixes that.
    """
    now = now or datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    if now.weekday() >= 5:
        return False
    if is_nse_holiday(now):
        return False
    hhmm = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= hhmm <= 15 * 60 + 30


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = fetch_candles("RELIANCE", "15m", 5)
    print(df.tail())
    print(f"Rows: {len(df)}")

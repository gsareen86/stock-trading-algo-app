"""
Scorecard pillar inputs — fundamental & market context for a candidate.

Each function returns a 0-100 score (higher = better) or None when the data
isn't available, in which case the composite simply renormalises over the
pillars that *are* present (see positional/scorer.py).

Sources are tables that already exist: lt_quality (quality), pos_universe
(valuation inputs), news (sentiment). Relative momentum is computed from the
stock's daily candles vs NIFTY 50.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd

log = logging.getLogger(__name__)


def _base(ticker: str) -> str:
    """Strip the exchange suffix used by the DB tables."""
    return ticker.replace(".NS", "").replace(".BO", "").strip()


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def quality_pillar(ticker: str) -> Optional[float]:
    """lt_quality.total_score (0-100), or None if the stock hasn't been scored."""
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT total_score FROM lt_quality WHERE ticker = ?", (_base(ticker),)
            ).fetchone()
        if row and row["total_score"] is not None:
            return _clip(float(row["total_score"]))
    except Exception as e:
        log.debug("[pillars] quality lookup failed for %s: %s", ticker, e)
    return None


def valuation_pillar(ticker: str) -> Optional[float]:
    """PEG-style valuation score from pos_universe (PE relative to sales growth).

    Cheap-for-the-growth scores high; richly valued or loss-making scores low.
    """
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT pe_ratio, sales_growth FROM pos_universe WHERE ticker = ?",
                (_base(ticker),),
            ).fetchone()
    except Exception as e:
        log.debug("[pillars] valuation lookup failed for %s: %s", ticker, e)
        return None

    if not row:
        return None
    pe = row["pe_ratio"]
    growth = row["sales_growth"]

    if pe is None or pe <= 0:
        return 45.0  # loss-making / missing PE — mild uncertainty discount
    pe = float(pe)

    # No / negative growth: judge on absolute PE alone.
    if growth is None or growth <= 0:
        if pe <= 15:
            return 60.0
        if pe <= 30:
            return 45.0
        return 30.0

    peg = pe / float(growth)
    # Piecewise map of PEG → score (lower PEG = cheaper for the growth).
    if peg <= 1.0:
        score = 90.0
    elif peg <= 1.5:
        score = 78.0
    elif peg <= 2.0:
        score = 65.0
    elif peg <= 2.5:
        score = 52.0
    elif peg <= 4.0:
        score = 38.0
    else:
        score = 22.0

    # Penalise nosebleed absolute PE even when growth is high.
    if pe > 80:
        score -= 12.0
    return _clip(score)


def nifty_returns() -> Tuple[Optional[float], Optional[float]]:
    """NIFTY 50 (^NSEI) 3-month and 6-month % returns. (None, None) on failure."""
    try:
        from data.fetcher import fetch_candles
        df = fetch_candles("^NSEI", interval="1d", days=200)
        if df is None or len(df) < 130:
            return None, None
        close = df["Close"].astype(float)
        n = len(close)
        i3 = min(63, n - 1)
        i6 = min(126, n - 1)
        r3 = (float(close.iloc[-1]) - float(close.iloc[-i3])) / float(close.iloc[-i3]) * 100
        r6 = (float(close.iloc[-1]) - float(close.iloc[-i6])) / float(close.iloc[-i6]) * 100
        return r3, r6
    except Exception as e:
        log.debug("[pillars] nifty returns failed: %s", e)
        return None, None


def relative_momentum_pillar(
    df: pd.DataFrame,
    nifty_ret_3m: Optional[float],
    nifty_ret_6m: Optional[float],
) -> Optional[float]:
    """Relative strength vs NIFTY over 3M + 6M, mapped to 0-100 (50 = matches index)."""
    if df is None or nifty_ret_3m is None or nifty_ret_6m is None:
        return None
    try:
        close = df["Close"].astype(float)
        n = len(close)
        if n < 130:
            return None
        i3 = min(63, n - 1)
        i6 = min(126, n - 1)
        r3 = (float(close.iloc[-1]) - float(close.iloc[-i3])) / float(close.iloc[-i3]) * 100
        r6 = (float(close.iloc[-1]) - float(close.iloc[-i6])) / float(close.iloc[-i6]) * 100
    except Exception:
        return None

    rs = (r3 - nifty_ret_3m) + (r6 - nifty_ret_6m)
    # ±37.5% combined relative strength maps to the 0-100 extremes.
    return round(_clip(50.0 + rs * 1.333), 1)


def sentiment_pillar(ticker: str, days: int = 14) -> Optional[float]:
    """Average recent news sentiment (-1..+1) mapped to 0-100; None if no news."""
    try:
        from db.models import get_conn
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        base = _base(ticker)
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT sentiment FROM news
                   WHERE tickers LIKE ? AND ts >= ? AND sentiment IS NOT NULL""",
                (f"%{base}%", cutoff),
            ).fetchall()
        vals = [float(r["sentiment"]) for r in rows if r["sentiment"] is not None]
        if not vals:
            return None
        avg = sum(vals) / len(vals)
        return round(_clip(50.0 + avg * 50.0), 1)
    except Exception as e:
        log.debug("[pillars] sentiment lookup failed for %s: %s", ticker, e)
        return None

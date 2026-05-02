"""
ATR-based exit logic + market-regime trend filter.

Why this module exists
----------------------
The legacy bot used fixed 5%/10% stop-loss / take-profit. On 15-min Indian
intraday, 5% noise drawdowns are routine while 10% intraday gains are rare —
which structurally produces a sub-33% win rate (you hit stop on noise way
before reaching target). The fix: volatility-normalise everything against
ATR(14), and add a partial-profit + trailing-stop overlay so that a winning
trade locks in some gain and lets the rest run.

Public API
----------
``compute_atr(df, period=14)``         -> latest ATR scalar (Wilder).
``atr_targets(entry, atr)``            -> dict with stop_loss / t1 / take_profit.
``nifty_trend_ok()``                   -> bool — last 15-min close > EMA20?
``trail_stop_after_t1(hwm, atr)``      -> new trailing stop level.

References for the math:
- ATR original: Wilder, *New Concepts in Technical Trading Systems* (1978).
- Volatility-stops survey: https://www.investopedia.com/articles/trading/08/atr.asp
- VanTharp's "Position sizing using ATR" — Dr. Van K. Tharp.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from config import (
    ATR_MAX_PCT_OF_PRICE,
    ATR_MIN_PCT_OF_PRICE,
    ATR_PERIOD,
    ATR_STOP_MULT,
    ATR_T1_MULT,
    ATR_TP_MULT,
    NIFTY_TREND_EMA_PERIOD,
    NIFTY_TREND_INTERVAL,
    NIFTY_TREND_LOOKBACK_DAYS,
    NIFTY_TREND_TICKER,
    TRAIL_ATR_MULT,
)

log = logging.getLogger(__name__)


# ---------- ATR ----------

def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> Optional[float]:
    """
    Wilder's ATR — the same formula used by virtually every retail charting
    package. Returns the most recent ATR as a scalar, or None if there isn't
    enough data.

    Implementation note: we use the True Range = max(high-low, |high-prev_close|,
    |low-prev_close|) and smooth with Wilder's EMA (alpha = 1/period). The `ta`
    library is already a dependency (requirements.txt) but rolling its API
    requires more boilerplate than this 8-line implementation; we keep it
    inline.
    """
    if df is None or df.empty or len(df) < period + 1:
        return None
    try:
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        close = df["Close"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat([
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        # Wilder's smoothing == EMA with alpha = 1/period.
        atr_series = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        atr = float(atr_series.iloc[-1])
        if not (atr > 0):
            return None
        return atr
    except Exception as e:
        log.debug("compute_atr failed: %s", e)
        return None


def atr_targets(entry: float, atr: float) -> dict:
    """Compute (stop_loss, t1_target, take_profit) from entry price + ATR.

    Validates the ATR is in a sane range — a 0.1% ATR usually means a stale
    low-volume candle, and >8% means the stock is moving too fast for our
    risk model. In either case the caller should fall back to fixed-pct
    exits (returns ``ok=False``).
    """
    if entry <= 0 or atr is None or atr <= 0:
        return {"ok": False, "reason": "invalid entry or ATR"}

    atr_pct = atr / entry
    if atr_pct < ATR_MIN_PCT_OF_PRICE:
        return {"ok": False, "reason": f"ATR too tight ({atr_pct:.4f} < {ATR_MIN_PCT_OF_PRICE})"}
    if atr_pct > ATR_MAX_PCT_OF_PRICE:
        return {"ok": False, "reason": f"ATR too wide ({atr_pct:.4f} > {ATR_MAX_PCT_OF_PRICE})"}

    sl = entry - ATR_STOP_MULT * atr
    t1 = entry + ATR_T1_MULT * atr
    tp = entry + ATR_TP_MULT * atr
    return {
        "ok": True,
        "stop_loss": round(sl, 2),
        "t1_target": round(t1, 2),
        "take_profit": round(tp, 2),
        "atr": round(atr, 4),
        "atr_pct": round(atr_pct * 100, 2),
    }


def trail_stop_after_t1(high_water_mark: float, atr_at_entry: float) -> float:
    """After T1 fires, the stop trails the high-water mark by 1*ATR.

    We use ATR_AT_ENTRY (not a recomputed live ATR) so the trail distance is
    deterministic from the position's perspective — it never widens just
    because volatility expands mid-trade, which would defeat the lock-in.
    """
    return round(high_water_mark - TRAIL_ATR_MULT * atr_at_entry, 2)


def atr_targets_short(entry: float, atr: float) -> dict:
    """Mirror image of :func:`atr_targets` for SHORT positions.

    For a short:
        stop_loss   = entry + 1.5*ATR  (price going UP hurts a short)
        t1_target   = entry - 1.0*ATR  (first profit milestone)
        take_profit = entry - 3.0*ATR  (final cover)
    """
    if entry <= 0 or atr is None or atr <= 0:
        return {"ok": False, "reason": "invalid entry or ATR"}

    atr_pct = atr / entry
    if atr_pct < ATR_MIN_PCT_OF_PRICE:
        return {"ok": False, "reason": f"ATR too tight ({atr_pct:.4f})"}
    if atr_pct > ATR_MAX_PCT_OF_PRICE:
        return {"ok": False, "reason": f"ATR too wide ({atr_pct:.4f})"}

    sl = entry + ATR_STOP_MULT * atr
    t1 = entry - ATR_T1_MULT * atr
    tp = entry - ATR_TP_MULT * atr
    return {
        "ok": True,
        "stop_loss": round(sl, 2),
        "t1_target": round(t1, 2),
        "take_profit": round(tp, 2),
        "atr": round(atr, 4),
        "atr_pct": round(atr_pct * 100, 2),
    }


def trail_stop_after_t1_short(low_water_mark: float, atr_at_entry: float) -> float:
    """For a SHORT runner, the trailing stop sits ABOVE the lowest price
    seen since entry. Stops only ratchet DOWN (never widen).
    """
    return round(low_water_mark + TRAIL_ATR_MULT * atr_at_entry, 2)


# ---------- Market-regime / trend filter ----------

def _nifty_15m_df(force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """Fetch (cached) 15-min NIFTY 50 candles. Used for the trend filter."""
    # Lazy import keeps startup time low and avoids circular deps.
    try:
        from data.fetcher import fetch_candles
    except Exception as e:
        log.warning("fetcher import failed in atr_exits: %s", e)
        return None
    df = fetch_candles(
        NIFTY_TREND_TICKER,
        interval=NIFTY_TREND_INTERVAL,
        days=NIFTY_TREND_LOOKBACK_DAYS,
        use_cache=not force_refresh,
    )
    if df is None or df.empty:
        return None
    return df


def nifty_trend_ok(force_refresh: bool = False) -> tuple[bool, str]:
    """Backwards-compat boolean gate.

    Wraps :func:`nifty_regime` and returns True only when regime != "bearish".
    Older callers that just want a yes/no on longs can keep using this.
    """
    regime, reason = nifty_regime(force_refresh=force_refresh)
    return regime != "bearish", reason


# Threshold (in percent) below which we consider the index "rangebound" —
# i.e. close is too near the EMA20 to call it a trend in either direction.
# Empirically, on 15-min NIFTY this matches what most traders eyeball as
# "sideways consolidation". Tune via experience.
NIFTY_NEUTRAL_BAND_PCT = 0.15


def nifty_regime(force_refresh: bool = False) -> tuple[str, str]:
    """Classify the NIFTY 50 regime as one of:

        "bullish"   → last 15-min close > EMA20 by more than NIFTY_NEUTRAL_BAND_PCT
        "bearish"   → last 15-min close < EMA20 by more than NIFTY_NEUTRAL_BAND_PCT
        "neutral"   → close is within ±NIFTY_NEUTRAL_BAND_PCT of EMA20 (rangebound)

    Returns ``(regime, human_reason)``. On any data-fetch failure we
    default to "neutral" so the bot can still place mean-reversion-style
    trades in either direction without halting.
    """
    df = _nifty_15m_df(force_refresh=force_refresh)
    if df is None or df.empty or len(df) < NIFTY_TREND_EMA_PERIOD + 1:
        return "neutral", "regime: insufficient data — defaulting to neutral"
    try:
        close = df["Close"].astype(float)
        ema = close.ewm(span=NIFTY_TREND_EMA_PERIOD, adjust=False).mean()
        last_close = float(close.iloc[-1])
        last_ema = float(ema.iloc[-1])
        delta_pct = (last_close - last_ema) / last_ema * 100
        if delta_pct > NIFTY_NEUTRAL_BAND_PCT:
            regime = "bullish"
        elif delta_pct < -NIFTY_NEUTRAL_BAND_PCT:
            regime = "bearish"
        else:
            regime = "neutral"
        return regime, (
            f"NIFTY {last_close:.0f} vs EMA{NIFTY_TREND_EMA_PERIOD} "
            f"{last_ema:.0f} ({delta_pct:+.2f}%) → {regime}"
        )
    except Exception as e:
        log.warning("nifty_regime failed: %s", e)
        return "neutral", f"regime: error ({e}) — defaulting to neutral"

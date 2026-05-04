"""
Positional risk management.

Key differences from intraday:
  - Wider ATR multipliers (2× stop, 4× target) on daily ATR
  - Delivery STT costs (0.1% buy + 0.1% sell vs 0.025% sell-only for intraday)
  - Overnight gap risk: hard stop on daily close, not intra-day price
  - Time stop: exit flat positions after POSITIONAL_TIME_STOP_DAYS
  - Event guard: auto-exit N days before known earnings/dividend dates
  - Correlation check: reject new entries in stocks correlated > 0.75 to existing ones
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    BROKERAGE_PCT,
    BROKERAGE_PER_ORDER,
    EXCHANGE_TXN_CHARGE,
    GST_RATE,
    INITIAL_CAPITAL,
    IST,
    POSITIONAL_ATR_PERIOD,
    POSITIONAL_ATR_STOP_MULT,
    POSITIONAL_ATR_T1_MULT,
    POSITIONAL_ATR_TP_MULT,
    POSITIONAL_CAPITAL_PCT,
    POSITIONAL_EVENT_GUARD_DAYS,
    POSITIONAL_MAX_POSITION_PCT,
    POSITIONAL_MAX_POSITIONS,
    POSITIONAL_RISK_PCT,
    POSITIONAL_TIME_STOP_DAYS,
    POSITIONAL_TRAIL_ATR_MULT,
    SEBI_CHARGES,
    SLIPPAGE_PCT,
    STAMP_DUTY_DELIVERY_PCT,
    STT_DELIVERY_BUY_PCT,
    STT_DELIVERY_SELL_PCT,
)
from db.models import get_conn

log = logging.getLogger(__name__)

POSITIONAL_POOL = INITIAL_CAPITAL * POSITIONAL_CAPITAL_PCT


# ---------- Cost model (delivery) ----------

def compute_delivery_costs(side: str, price: float, qty: int) -> float:
    """Compute total trading cost for a delivery (positional) order."""
    gross = price * qty
    brokerage = min(BROKERAGE_PER_ORDER, gross * BROKERAGE_PCT)
    stt = gross * (STT_DELIVERY_BUY_PCT if side == "BUY" else STT_DELIVERY_SELL_PCT)
    exchange = gross * EXCHANGE_TXN_CHARGE
    sebi = gross * SEBI_CHARGES
    gst = (brokerage + exchange + sebi) * GST_RATE
    stamp = gross * STAMP_DUTY_DELIVERY_PCT if side == "BUY" else 0.0
    return round(brokerage + stt + exchange + sebi + gst + stamp, 4)


def delivery_fill_price(side: str, price: float) -> float:
    slip = price * SLIPPAGE_PCT
    return price + slip if side == "BUY" else price - slip


# ---------- Position sizing ----------

def positional_position_size(
    entry_price: float,
    atr: float,
    pool_cash: float,
) -> int:
    """
    ATR-based position size for delivery trades.
    Risk = POSITIONAL_RISK_PCT × pool_cash
    Stop distance = POSITIONAL_ATR_STOP_MULT × ATR
    Shares = Risk / Stop distance, capped at POSITIONAL_MAX_POSITION_PCT × pool.
    """
    stop_distance = POSITIONAL_ATR_STOP_MULT * atr
    if stop_distance <= 0 or entry_price <= 0:
        return 0
    risk_amount = POSITIONAL_RISK_PCT * pool_cash
    qty = int(risk_amount / stop_distance)
    max_qty = int(pool_cash * POSITIONAL_MAX_POSITION_PCT / entry_price)
    qty = min(qty, max_qty)
    return max(qty, 0)


def compute_daily_atr(df: pd.DataFrame, period: int = POSITIONAL_ATR_PERIOD) -> float:
    if df is None or len(df) < period + 2:
        return 0.0
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = float(tr.ewm(com=period - 1, adjust=False).mean().iloc[-1])
    # Sanity bounds: ATR should be 0.3%–8% of price
    price = float(close.iloc[-1])
    if price > 0:
        atr = max(atr, price * 0.003)
        atr = min(atr, price * 0.08)
    return round(atr, 4)


def compute_atr_targets(entry_price: float, atr: float) -> dict:
    return {
        "stop_loss":    round(entry_price - POSITIONAL_ATR_STOP_MULT * atr, 2),
        "t1_target":    round(entry_price + POSITIONAL_ATR_T1_MULT * atr, 2),
        "tp_target":    round(entry_price + POSITIONAL_ATR_TP_MULT * atr, 2),
        "atr":          round(atr, 4),
    }


# ---------- Open-position checks ----------

def can_open_positional(pool_cash: float) -> bool:
    """True if we can open another positional position."""
    try:
        with get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM positions "
                "WHERE status='OPEN' AND trade_type='positional'"
            ).fetchone()[0]
        return count < POSITIONAL_MAX_POSITIONS and pool_cash > 0
    except Exception as e:
        log.warning("can_open_positional check failed: %s", e)
        return False


def get_positional_pool_cash() -> float:
    """Estimate available cash in the positional pool."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT entry_price, quantity FROM positions "
                "WHERE status='OPEN' AND trade_type='positional'"
            ).fetchall()
        invested = sum(r["entry_price"] * r["quantity"] for r in rows)
        return max(POSITIONAL_POOL - invested, 0.0)
    except Exception:
        return POSITIONAL_POOL


# ---------- Exit management ----------

def check_positional_exits(pos: dict, current_price: float, days_held: int) -> Optional[str]:
    """
    Evaluate whether a positional position should be exited.
    Returns exit reason string or None.

    pos dict keys: entry_price, stop_loss, t1_target, high_water_mark,
                   t1_taken, initial_quantity, quantity, atr_at_entry
    """
    entry = float(pos.get("entry_price", 0))
    stop = float(pos.get("stop_loss", 0))
    t1 = float(pos.get("t1_target", 0))
    hwm = float(pos.get("high_water_mark", current_price))
    t1_taken = int(pos.get("t1_taken", 0))
    atr = float(pos.get("atr_at_entry", 0))

    # Hard stop: daily close below stop
    if stop > 0 and current_price <= stop:
        return f"STOP: price {current_price:.2f} ≤ stop {stop:.2f}"

    # T1 target partial exit (caller handles quantity reduction)
    if not t1_taken and t1 > 0 and current_price >= t1:
        return "T1_PARTIAL"

    # Trailing stop after T1: hwm − 1.5×ATR
    if t1_taken and atr > 0:
        trail_stop = hwm - POSITIONAL_TRAIL_ATR_MULT * atr
        if current_price < trail_stop:
            return f"TRAIL_STOP: price {current_price:.2f} < trail {trail_stop:.2f}"

    # Time stop: flat position after N days
    pnl_pct = (current_price - entry) / (entry + 1e-10) * 100
    if days_held >= POSITIONAL_TIME_STOP_DAYS and abs(pnl_pct) < 3.0:
        return f"TIME_STOP: {days_held}d held, flat at {pnl_pct:+.1f}%"

    # Max hold days exceeded
    if days_held >= 30:
        return f"MAX_HOLD: {days_held}d — mandatory exit"

    return None


def check_event_guard(ticker: str) -> Optional[str]:
    """
    Check for upcoming corporate events (earnings, dividends) within
    POSITIONAL_EVENT_GUARD_DAYS trading days. Returns event description or None.

    Uses yfinance calendar data — best-effort only.
    """
    try:
        import yfinance as yf
        from data.universe import to_yf_ticker
        yf_ticker = to_yf_ticker(ticker) if not ticker.endswith((".NS", ".BO")) else ticker
        t = yf.Ticker(yf_ticker)
        cal = t.calendar
        if cal is None or cal.empty:
            return None
        now = datetime.now(IST).date()
        guard = timedelta(days=POSITIONAL_EVENT_GUARD_DAYS)
        for col in cal.columns:
            val = cal[col].iloc[0] if len(cal) > 0 else None
            if val is None:
                continue
            try:
                event_date = pd.Timestamp(val).date()
                if now <= event_date <= now + guard:
                    return f"upcoming {col} on {event_date}"
            except Exception:
                continue
    except Exception as e:
        log.debug("event guard check failed for %s: %s", ticker, e)
    return None


# ---------- Correlation filter ----------

def is_correlated_to_open_positions(ticker: str, df_new: pd.DataFrame,
                                    threshold: float = 0.75) -> bool:
    """
    Return True if the new ticker has correlation > threshold with any
    currently open positional position (60-day daily returns).
    """
    if df_new is None or df_new.empty:
        return False
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT ticker FROM positions "
                "WHERE status='OPEN' AND trade_type='positional'"
            ).fetchall()
        open_tickers = [r["ticker"] for r in rows if r["ticker"] != ticker]
        if not open_tickers:
            return False

        from data.fetcher import fetch_candles
        new_ret = df_new["Close"].astype(float).pct_change().dropna().tail(60)

        for ot in open_tickers:
            ot_df = fetch_candles(ot, interval="1d", days=90)
            if ot_df is None or ot_df.empty:
                continue
            ot_ret = ot_df["Close"].astype(float).pct_change().dropna().tail(60)
            aligned = pd.concat([new_ret, ot_ret], axis=1, join="inner").dropna()
            if len(aligned) < 30:
                continue
            corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
            if corr > threshold:
                log.info("positional: %s corr=%.2f with open %s — skipping", ticker, corr, ot)
                return True
    except Exception as e:
        log.debug("correlation check failed for %s: %s", ticker, e)
    return False

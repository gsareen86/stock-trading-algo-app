"""
Positional Risk Management — Minervini method.

Exit rules (in priority order):
  1. Hard stop:         price < entry × (1 - HARD_STOP_PCT)  → immediate SELL
  2. Trailing EMA stop: 2 consecutive daily closes below 21 EMA → SELL ALERT
  3. Time stop:         <2% move over 15 trading days → SELL (capital churning)
  4. Re-entry alert:    exited within 14 days, closes above 21 EMA on high vol

Position sizing:
  Capital per trade = POSITIONAL_CAPITAL / MAX_POSITIONS (equal weight: 20K each)
  Modified by regime size_multiplier (0.35 when DEFENSIVE, 1.0 when AGGRESSIVE)
  Quantity = floor(allocation / entry_price)

Delivery costs (different from intraday):
  STT  0.1% on buy + 0.1% on sell (vs 0.025% sell-only for intraday)
  Stamp 0.015% on buy only
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from config import (
    BROKERAGE_PCT,
    BROKERAGE_PER_ORDER,
    EXCHANGE_TXN_CHARGE,
    GST_RATE,
    IST,
    POSITIONAL_CAPITAL,
    POSITIONAL_EMA_TRAIL_CONSECUTIVE,
    POSITIONAL_EMA_TRAIL_PERIOD,
    POSITIONAL_HARD_STOP_PCT,
    POSITIONAL_MAX_POSITIONS,
    POSITIONAL_MAX_POSITION_PCT,
    POSITIONAL_REENTRY_VOL_MULT,
    POSITIONAL_REENTRY_WINDOW_DAYS,
    POSITIONAL_TIME_STOP_DAYS,
    POSITIONAL_TIME_STOP_MIN_MOVE_PCT,
    SEBI_CHARGES,
    SLIPPAGE_PCT,
    STAMP_DUTY_DELIVERY_PCT,
    STT_DELIVERY_BUY_PCT,
    STT_DELIVERY_SELL_PCT,
)

log = logging.getLogger(__name__)


# ── Cost model (delivery / positional) ───────────────────────────────────────

def compute_delivery_costs(side: str, price: float, qty: int) -> float:
    gross = price * qty
    brokerage = min(BROKERAGE_PER_ORDER, gross * BROKERAGE_PCT)
    stt    = gross * (STT_DELIVERY_BUY_PCT if side == "BUY" else STT_DELIVERY_SELL_PCT)
    exch   = gross * EXCHANGE_TXN_CHARGE
    sebi   = gross * SEBI_CHARGES
    gst    = (brokerage + exch + sebi) * GST_RATE
    stamp  = (gross * STAMP_DUTY_DELIVERY_PCT) if side == "BUY" else 0.0
    return round(brokerage + stt + exch + sebi + gst + stamp, 4)


def delivery_fill_price(side: str, price: float,
                        slippage_pct: Optional[float] = None) -> float:
    """Fill with slippage. Microcaps get the wider tier (0.4% vs 0.05%) —
    pass slippage_pct explicitly, or use fill_slippage_pct() per ticker."""
    slip = price * (slippage_pct if slippage_pct is not None else SLIPPAGE_PCT)
    return price + slip if side == "BUY" else price - slip


def fill_slippage_pct(ticker: str) -> float:
    """Slippage tier for a ticker: SLIPPAGE_MICROCAP_PCT below the microcap
    threshold, the standard large-cap figure above it."""
    try:
        from config import SLIPPAGE_MICROCAP_PCT
        from data.hygiene import is_microcap
        if is_microcap(ticker):
            return SLIPPAGE_MICROCAP_PCT
    except Exception:
        pass
    return SLIPPAGE_PCT


# ── Position sizing ───────────────────────────────────────────────────────────

def positional_position_size(entry_price: float, size_multiplier: float = 1.0) -> int:
    """
    Equal-weight sizing: POSITIONAL_CAPITAL / MAX_POSITIONS, adjusted by regime multiplier.
    Returns quantity (shares), floored to whole shares.
    Capped at POSITIONAL_MAX_POSITION_PCT of total capital.
    """
    if entry_price <= 0:
        return 0
    base_alloc   = POSITIONAL_CAPITAL / POSITIONAL_MAX_POSITIONS   # e.g. 20,000
    adj_alloc    = base_alloc * size_multiplier
    max_alloc    = POSITIONAL_CAPITAL * POSITIONAL_MAX_POSITION_PCT
    final_alloc  = min(adj_alloc, max_alloc)
    return max(1, int(final_alloc / entry_price))


def positional_position_size_risk(
    entry_price: float,
    stop_price: float,
    size_multiplier: float = 1.0,
    cash_available: Optional[float] = None,
    adv_cr: Optional[float] = None,
) -> int:
    """
    Risk-based sizing: qty = risk_amount / (entry − stop).

    A tight stop (e.g. a 3% VCP pivot) naturally earns a bigger position than
    a loose 8% one for the same rupee risk — the Minervini logic the scanner
    encodes, applied to sizing. Caps, in order:
      * POSITIONAL_MAX_POSITION_PCT of the pool
      * available pool cash
      * MAX_POSITION_PCT_OF_ADV of the stock's median daily traded value —
        the rule that scales with the account and automatically shrinks
        positions in thin names (you must be able to exit in ~a day).
    Returns 0 when inputs are invalid.
    """
    from config import POSITIONAL_RISK_PCT_POOL, MAX_POSITION_PCT_OF_ADV

    if entry_price <= 0 or stop_price <= 0 or stop_price >= entry_price:
        return 0
    risk_amount = POSITIONAL_CAPITAL * POSITIONAL_RISK_PCT_POOL * size_multiplier
    per_share_risk = entry_price - stop_price
    qty = int(risk_amount / per_share_risk)

    max_alloc = POSITIONAL_CAPITAL * POSITIONAL_MAX_POSITION_PCT
    if cash_available is not None:
        max_alloc = min(max_alloc, cash_available)
    if adv_cr is not None and adv_cr > 0:
        max_alloc = min(max_alloc, adv_cr * 1e7 * MAX_POSITION_PCT_OF_ADV)
    qty = min(qty, int(max_alloc / entry_price))
    return max(qty, 0)


def compute_partial_trigger(entry_price: float, hard_stop: float) -> Optional[float]:
    """Price at which the +R partial de-risk fires (entry + R × multiple).
    R = entry − initial hard stop. None when the stop is invalid."""
    from config import POSITIONAL_PARTIAL_AT_R

    if entry_price <= 0 or hard_stop <= 0 or hard_stop >= entry_price:
        return None
    r = entry_price - hard_stop
    return round(entry_price + POSITIONAL_PARTIAL_AT_R * r, 2)


def compute_hard_stop(entry_price: float) -> float:
    """8% hard stop below entry price."""
    return round(entry_price * (1 - POSITIONAL_HARD_STOP_PCT), 2)


def compute_target(entry_price: float, atr: float = 0.0) -> float:
    """
    Target: 2× risk (16% if hard stop = 8%) or 3× ATR if ATR available.
    Returns the higher of the two for an aggressive but realistic target.
    """
    target_from_stop = entry_price * (1 + 2 * POSITIONAL_HARD_STOP_PCT)
    if atr > 0:
        target_from_atr = entry_price + 3 * atr
        return round(max(target_from_stop, target_from_atr), 2)
    return round(target_from_stop, 2)


def compute_ema21(df: pd.DataFrame) -> float:
    """Compute current 21-day EMA from daily OHLCV dataframe."""
    if df is None or len(df) < 21:
        return 0.0
    ema = df["Close"].astype(float).ewm(span=21, adjust=False).mean()
    return float(ema.iloc[-1])


# ── Available positional pool cash ───────────────────────────────────────────

def get_positional_cash() -> float:
    """
    Estimate available cash in the positional pool:
    POSITIONAL_CAPITAL minus cost of all OPEN pos_positions.
    """
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT entry_price, quantity FROM pos_positions WHERE status='OPEN'"
            ).fetchall()
        invested = sum(float(r["entry_price"]) * int(r["quantity"]) for r in rows)
        return max(POSITIONAL_CAPITAL - invested, 0.0)
    except Exception:
        return POSITIONAL_CAPITAL


def count_open_positions() -> int:
    try:
        from db.models import get_conn
        with get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM pos_positions WHERE status='OPEN'"
            ).fetchone()[0]
    except Exception:
        return 0


def can_open_position() -> bool:
    return count_open_positions() < POSITIONAL_MAX_POSITIONS and get_positional_cash() > 0


# ── Exit logic ────────────────────────────────────────────────────────────────

def check_hard_stop(pos: dict, current_price: float) -> Optional[str]:
    """Returns exit reason if hard stop triggered."""
    hard_stop = float(pos.get("hard_stop", 0))
    if hard_stop > 0 and current_price <= hard_stop:
        return f"HARD_STOP: {current_price:.2f} <= stop {hard_stop:.2f}"
    return None


def check_ema_trailing_stop(pos: dict, df: pd.DataFrame) -> Optional[str]:
    """
    EMA trailing stop: POSITIONAL_EMA_TRAIL_CONSECUTIVE consecutive daily closes
    below the POSITIONAL_EMA_TRAIL_PERIOD EMA → SELL ALERT. Sets the true
    trailing below-EMA count on the pos dict (caller persists to DB).
    Returns exit reason or None.
    """
    need = POSITIONAL_EMA_TRAIL_CONSECUTIVE
    if df is None or len(df) < POSITIONAL_EMA_TRAIL_PERIOD + need:
        return None

    close = df["Close"].astype(float)
    ema = close.ewm(span=POSITIONAL_EMA_TRAIL_PERIOD, adjust=False).mean()

    # Count trailing consecutive daily closes below the EMA.
    below = (close < ema).tolist()
    consecutive = 0
    for flag in reversed(below):
        if flag:
            consecutive += 1
        else:
            break
    pos["below_ema_consecutive"] = consecutive

    if consecutive >= need:
        return (f"EMA_TRAIL: {consecutive} consecutive closes below "
                f"{POSITIONAL_EMA_TRAIL_PERIOD} EMA "
                f"(price={float(close.iloc[-1]):.2f} EMA={float(ema.iloc[-1]):.2f})")
    return None


def check_time_stop(pos: dict) -> Optional[str]:
    """
    Time stop: if position moves < TIME_STOP_MIN_MOVE_PCT over the stop window,
    exit to free up capital.

    The window is the entering strategy's expected hold (pos.time_stop_days,
    set at entry from the scan's est_hold_days) when
    POSITIONAL_TIME_STOP_USE_STRATEGY is on; else the flat config default.
    """
    from config import POSITIONAL_TIME_STOP_USE_STRATEGY

    stop_days = POSITIONAL_TIME_STOP_DAYS
    if POSITIONAL_TIME_STOP_USE_STRATEGY:
        try:
            custom = int(pos.get("time_stop_days") or 0)
            if custom > 0:
                stop_days = custom
        except (TypeError, ValueError):
            pass

    days_held = int(pos.get("days_held", 0))
    if days_held < stop_days:
        return None
    entry = float(pos.get("entry_price", 1))
    peak  = float(pos.get("peak_price") or entry)
    # Max excursion (upward)
    max_move_pct = (peak - entry) / entry * 100
    if max_move_pct < POSITIONAL_TIME_STOP_MIN_MOVE_PCT:
        return (f"TIME_STOP: {days_held} days held, "
                f"max gain only {max_move_pct:.1f}% < {POSITIONAL_TIME_STOP_MIN_MOVE_PCT}%")
    return None


def check_reentry(ticker: str, df: pd.DataFrame) -> Optional[str]:
    """
    Re-entry alert: stock exited within last REENTRY_WINDOW_DAYS, now reclaiming
    21 EMA on high volume → possible re-entry opportunity.
    Returns alert string or None.
    """
    if df is None or len(df) < 22:
        return None
    from datetime import datetime, timedelta
    try:
        from db.models import get_conn
        cutoff = (datetime.now() - timedelta(days=POSITIONAL_REENTRY_WINDOW_DAYS)).date().isoformat()
        with get_conn() as conn:
            row = conn.execute(
                """SELECT exit_date, exit_price FROM pos_positions
                   WHERE ticker=? AND status='CLOSED' AND exit_date >= ?
                   ORDER BY id DESC LIMIT 1""",
                (ticker, cutoff),
            ).fetchone()
        if not row:
            return None
    except Exception:
        return None

    close  = df["Close"].astype(float)
    vol    = df["Volume"].astype(float)
    ema21  = close.ewm(span=21, adjust=False).mean()
    avg_vol = float(vol.tail(20).mean())

    price_today  = float(close.iloc[-1])
    ema_today    = float(ema21.iloc[-1])
    vol_today    = float(vol.iloc[-1])

    if price_today > ema_today and vol_today > avg_vol * POSITIONAL_REENTRY_VOL_MULT:
        return (f"RE-ENTRY: {ticker} reclaiming 21 EMA on high volume "
                f"(price={price_today:.2f} EMA={ema_today:.2f} "
                f"vol={vol_today/avg_vol:.1f}x avg)")
    return None


def evaluate_exits(pos: dict, df: pd.DataFrame) -> Optional[str]:
    """
    Master exit check. Evaluates all exit conditions in priority order.
    Returns exit reason string or None (hold).
    """
    current_price = float(df["Close"].iloc[-1]) if df is not None and not df.empty else None
    if current_price is None:
        return None

    # 1. Hard stop (highest priority)
    reason = check_hard_stop(pos, current_price)
    if reason:
        return reason

    # 2. EMA trailing stop
    reason = check_ema_trailing_stop(pos, df)
    if reason:
        return reason

    # 3. Time stop
    reason = check_time_stop(pos)
    if reason:
        return reason

    return None

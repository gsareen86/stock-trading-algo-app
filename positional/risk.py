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


def delivery_fill_price(side: str, price: float) -> float:
    slip = price * SLIPPAGE_PCT
    return price + slip if side == "BUY" else price - slip


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
    EMA trailing stop: 2 consecutive daily closes below 21 EMA → SELL ALERT.
    Updates below_ema_consecutive count in the pos dict (caller persists to DB).
    Returns exit reason or None.
    """
    if df is None or len(df) < 22:
        return None

    close = df["Close"].astype(float)
    ema21 = close.ewm(span=21, adjust=False).mean()

    # Check the last 2 trading days
    last2_close = close.tail(2).values
    last2_ema   = ema21.tail(2).values

    below_today      = float(last2_close[-1]) < float(last2_ema[-1])
    below_yesterday  = len(last2_close) > 1 and float(last2_close[-2]) < float(last2_ema[-2])

    consecutive = int(pos.get("below_ema_consecutive", 0))

    if below_today and below_yesterday:
        # 2 consecutive closes below 21 EMA
        ema_val = float(last2_ema[-1])
        return (f"EMA_TRAIL: 2 consecutive closes below 21 EMA "
                f"(price={last2_close[-1]:.2f} EMA21={ema_val:.2f})")

    # Update consecutive counter (caller must persist this)
    pos["below_ema_consecutive"] = 1 if below_today else 0
    return None


def check_time_stop(pos: dict) -> Optional[str]:
    """
    Time stop: if position moves < TIME_STOP_MIN_MOVE_PCT over TIME_STOP_DAYS
    trading days, exit to free up capital.
    """
    days_held = int(pos.get("days_held", 0))
    if days_held < POSITIONAL_TIME_STOP_DAYS:
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

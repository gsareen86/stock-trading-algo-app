"""
Positional Trading Runner — EOD (End-of-Day) Scanner & Portfolio Manager.

Daily schedule:
  4:00 PM IST  — run_eod_scan():     scan fundamental universe, generate BUY alerts
  4:30 PM IST  — send_eod_summary(): send full Telegram report
  Monthly      — run_regime_check(): compute market regime (macro filter)

Position management (checked every day at EOD):
  1. Hard stop:     price < entry × (1 - 0.08)   → auto-exit (paper) or SELL alert
  2. EMA trailing:  2 consecutive closes below 21 EMA → SELL ALERT
  3. Time stop:     <2% move over 15 trading days  → SELL ALERT
  4. Re-entry:      exited within 14 days, reclaiming 21 EMA on high vol → alert

New entries (from EOD scan):
  - Score ≥ 60 + Trend Template passes → queue as BUY
  - Paper mode: auto-fill
  - Sharekhan/Zerodha: place real order via broker API

Capital: separate 1 Lakh pool (POSITIONAL_CAPITAL in config.py)
         does NOT mix with the intraday portfolio cash.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from config import (
    DEFAULT_MODE,
    IST,
    POSITIONAL_ALERT_TIME,
    POSITIONAL_SCAN_TIME,
)

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _positional_enabled() -> bool:
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT positional_enabled FROM bot_control WHERE id=1"
            ).fetchone()
        return bool(row and row["positional_enabled"])
    except Exception:
        return False


def _is_trading_day() -> bool:
    now = datetime.now(IST)
    return now.weekday() < 5  # Mon-Fri


def _fetch_daily_df(ticker: str):
    """Fetch 14 months of daily data for a ticker. Returns DataFrame or None."""
    try:
        import pandas as pd
        import yfinance as yf
        t = ticker if ticker.endswith((".NS", ".BO")) else ticker + ".NS"
        df = yf.download(t, period="14mo", interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        # yfinance >=0.2.x returns MultiIndex columns for single-ticker downloads;
        # flatten to a plain column index so downstream code gets Series, not DataFrames.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        log.debug("[pos_runner] fetch failed for %s: %s", ticker, e)
        return None


# ── Open a new position ───────────────────────────────────────────────────────

def _open_position(ticker: str, price: float, score: float,
                   scan_id: int, regime_flag: str) -> bool:
    """Place a BUY order and record in pos_positions + pos_trades."""
    from positional.risk import (
        positional_position_size, compute_hard_stop, compute_target,
        compute_delivery_costs, delivery_fill_price,
        get_positional_cash, can_open_position,
    )
    from positional.market_regime import current_size_multiplier
    from positional.broker import get_broker
    from db.models import get_conn, insert_returning_id

    if not can_open_position():
        log.info("[pos_runner] %s: max positions reached or no cash", ticker)
        return False

    size_mult = current_size_multiplier()
    qty       = positional_position_size(price, size_multiplier=size_mult)
    if qty <= 0:
        log.info("[pos_runner] %s: qty=0 at price=%.2f (insufficient capital)", ticker, price)
        return False

    # Place order
    broker = get_broker()
    result = broker.place_order(ticker, "BUY", qty, price)
    if not result.success:
        log.warning("[pos_runner] %s: order failed — %s", ticker, result.message)
        return False

    fill       = result.fill_price
    costs      = compute_delivery_costs("BUY", fill, qty)
    hard_stop  = compute_hard_stop(fill)
    target     = compute_target(fill)
    entry_date = datetime.now(IST).isoformat()

    try:
        with get_conn() as conn:
            pos_id = insert_returning_id(
                conn,
                """INSERT INTO pos_positions
                   (ticker, entry_date, entry_price, quantity, hard_stop,
                    ema_trail_stop, target_price, status, peak_price,
                    below_ema_consecutive, days_held, regime_at_entry, scan_id)
                   VALUES (?,?,?,?,?,?,?,?,?,0,0,?,?)""",
                (ticker, entry_date, fill, qty, hard_stop,
                 None, target, "OPEN", fill, regime_flag, scan_id),
            )
            conn.execute(
                """INSERT INTO pos_trades
                   (ts, ticker, side, quantity, price, costs, pnl, reason, position_id)
                   VALUES (?,?,?,?,?,?,0,?,?)""",
                (entry_date, ticker, "BUY", qty, fill, costs,
                 f"EOD scan entry score={score:.0f}", pos_id),
            )
    except Exception as e:
        log.error("[pos_runner] DB write failed for %s: %s", ticker, e)
        return False

    log.info("[pos_runner] OPENED: %s qty=%d fill=%.2f stop=%.2f target=%.2f broker=%s",
             ticker, qty, fill, hard_stop, target, broker.name)
    return True


# ── Close a position ──────────────────────────────────────────────────────────

def _close_position(pos: dict, current_price: float, reason: str) -> bool:
    """Place a SELL order and mark pos_positions as CLOSED."""
    from positional.risk import compute_delivery_costs, delivery_fill_price
    from positional.broker import get_broker
    from db.models import get_conn, insert_returning_id

    pos_id  = pos["id"]
    ticker  = pos["ticker"]
    qty     = int(pos["quantity"])
    entry   = float(pos["entry_price"])

    broker = get_broker()
    result = broker.place_order(ticker, "SELL", qty, current_price)
    fill   = result.fill_price if result.success else current_price

    costs  = compute_delivery_costs("SELL", fill, qty)
    pnl    = (fill - entry) * qty - costs
    pnl_pct= (fill - entry) / entry * 100
    ts     = datetime.now(IST).isoformat()

    try:
        with get_conn() as conn:
            conn.execute(
                """UPDATE pos_positions
                   SET status='CLOSED', exit_date=?, exit_price=?,
                       exit_reason=?, pnl=?, pnl_pct=?
                   WHERE id=?""",
                (ts, fill, reason, round(pnl, 2), round(pnl_pct, 2), pos_id),
            )
            insert_returning_id(
                conn,
                """INSERT INTO pos_trades
                   (ts, ticker, side, quantity, price, costs, pnl, reason, position_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ts, ticker, "SELL", qty, fill, costs, round(pnl, 2), reason, pos_id),
            )
    except Exception as e:
        log.error("[pos_runner] close DB write failed for %s: %s", ticker, e)
        return False

    pnl_tag = "+" if pnl >= 0 else ""
    log.info("[pos_runner] CLOSED: %s qty=%d fill=%.2f pnl=%s%.2f (%.1f%%) reason=%s",
             ticker, qty, fill, pnl_tag, pnl, pnl_pct, reason)

    # Telegram SELL alert
    try:
        from positional.alerts import send_sell_alert
        send_sell_alert(ticker, fill, reason, entry_price=entry)
    except Exception:
        pass

    return True


# ── Manual paper order (dashboard button) ────────────────────────────────────

def place_manual_order(ticker: str, price: float,
                       score: float = 0.0, qty_override: int = 0) -> dict:
    """
    Place a paper BUY order manually from the dashboard.

    Called when the user clicks 'Place Paper Order' on a scan result.
    Bypasses trading-day and positional_enabled checks — always executes
    in paper mode, purely for tracking and analytics.

    Args:
        ticker:       NSE ticker (e.g. 'CUMMINSIND.NS')
        price:        entry price (usually last scan price)
        score:        Minervini composite score from the scan
        qty_override: if > 0, override auto-calculated quantity

    Returns: {success, message, quantity, hard_stop, target}
    """
    from positional.risk import (
        positional_position_size, compute_hard_stop, compute_target,
        compute_delivery_costs, delivery_fill_price,
        get_positional_cash, can_open_position,
    )
    from positional.market_regime import current_size_multiplier, get_latest_regime
    from positional.broker import get_broker
    from db.models import get_conn, insert_returning_id

    regime = get_latest_regime()
    regime_flag = regime.get("flag", "NEUTRAL")
    size_mult = float(regime.get("size_multiplier", 0.70))

    if not can_open_position():
        return {"success": False,
                "message": "Max positions already open or insufficient capital."}

    qty = qty_override if qty_override > 0 else positional_position_size(price, size_multiplier=size_mult)
    if qty <= 0:
        return {"success": False,
                "message": f"Quantity 0 at ₹{price:,.2f} — insufficient capital in pool."}

    broker = get_broker()
    result = broker.place_order(ticker, "BUY", qty, price)
    if not result.success:
        return {"success": False, "message": f"Order rejected: {result.message}"}

    fill      = result.fill_price
    costs     = compute_delivery_costs("BUY", fill, qty)
    hard_stop = compute_hard_stop(fill)
    target    = compute_target(fill)
    entry_date = datetime.now(IST).isoformat()

    try:
        with get_conn() as conn:
            pos_id = insert_returning_id(
                conn,
                """INSERT INTO pos_positions
                   (ticker, entry_date, entry_price, quantity, hard_stop,
                    ema_trail_stop, target_price, status, peak_price,
                    below_ema_consecutive, days_held, regime_at_entry, scan_id)
                   VALUES (?,?,?,?,?,?,?,?,?,0,0,?,0)""",
                (ticker, entry_date, fill, qty, hard_stop,
                 None, target, "OPEN", fill, regime_flag),
            )
            conn.execute(
                """INSERT INTO pos_trades
                   (ts, ticker, side, quantity, price, costs, pnl, reason, position_id)
                   VALUES (?,?,?,?,?,?,0,'MANUAL_ENTRY',?)""",
                (entry_date, ticker, "BUY", qty, fill, costs, pos_id),
            )
    except Exception as e:
        log.error("[pos_runner] place_manual_order DB write failed: %s", e)
        return {"success": False, "message": f"DB write failed: {e}"}

    log.info(
        "[pos_runner] Manual paper order: BUY %d × %s @ ₹%.2f | stop=₹%.2f target=₹%.2f",
        qty, ticker, fill, hard_stop, target,
    )
    return {
        "success":   True,
        "message":   f"Paper BUY placed: {qty} × {ticker} @ ₹{fill:,.2f}",
        "quantity":  qty,
        "fill":      fill,
        "hard_stop": hard_stop,
        "target":    target,
    }


# ── EOD Exit Management ───────────────────────────────────────────────────────

def run_exit_checks() -> dict:
    """
    Check all OPEN pos_positions for exit conditions.
    Returns summary: {exited, sell_alerts, reentry_alerts, updated, errors}
    """
    if not _is_trading_day():
        return {"skipped": True, "reason": "non-trading day"}

    log.info("[pos_runner] === EXIT CHECK START ===")
    from positional.risk import evaluate_exits, check_reentry, compute_ema21
    from positional.alerts import send_sell_alert, send_reentry_alert
    from db.models import get_conn

    exited = 0
    sell_alerts_list: list[dict] = []
    reentry_alerts_list: list[dict] = []
    updated = 0
    errors  = 0

    try:
        with get_conn() as conn:
            positions = conn.execute(
                "SELECT * FROM pos_positions WHERE status='OPEN'"
            ).fetchall()
        positions = [dict(p) for p in positions]
    except Exception as e:
        log.error("[pos_runner] exit check DB read failed: %s", e)
        return {"errors": 1}

    for pos in positions:
        ticker = pos["ticker"]
        try:
            df = _fetch_daily_df(ticker)
            if df is None or df.empty:
                log.warning("[pos_runner] no data for %s — skipping exit check", ticker)
                continue

            current_price = float(df["Close"].iloc[-1])

            # Update peak price
            peak = float(pos.get("peak_price") or current_price)
            if current_price > peak:
                peak = current_price

            # Increment days_held
            days_held = int(pos.get("days_held", 0)) + 1

            # Evaluate exit
            exit_reason = evaluate_exits(pos, df)
            if exit_reason:
                _close_position(pos, current_price, exit_reason)
                sell_alerts_list.append({
                    "ticker": ticker,
                    "reason": exit_reason,
                    "current_price": current_price,
                })
                exited += 1
            else:
                # Update current EMA trail stop and counters
                ema21_val = compute_ema21(df)
                below_ema = int(pos.get("below_ema_consecutive", 0))
                if current_price < ema21_val:
                    below_ema += 1
                else:
                    below_ema = 0
                try:
                    with get_conn() as conn:
                        conn.execute(
                            """UPDATE pos_positions
                               SET peak_price=?, days_held=?,
                                   ema_trail_stop=?, below_ema_consecutive=?
                               WHERE id=?""",
                            (peak, days_held, ema21_val, below_ema, pos["id"]),
                        )
                except Exception as e:
                    log.debug("[pos_runner] update failed for %s: %s", ticker, e)
                updated += 1

            # Re-entry check (applies to stocks not currently held)
        except Exception as e:
            log.warning("[pos_runner] exit error for %s: %s", ticker, e)
            errors += 1

    # Re-entry alerts for recently closed positions
    try:
        with get_conn() as conn:
            cutoff = (datetime.now() - timedelta(days=14)).date().isoformat()
            watchlist = conn.execute(
                """SELECT DISTINCT ticker FROM pos_positions
                   WHERE status='CLOSED' AND exit_date >= ?""",
                (cutoff,),
            ).fetchall()
            open_tickers = {p["ticker"] for p in positions}
        for row in watchlist:
            ticker = row["ticker"]
            if ticker in open_tickers:
                continue
            try:
                df = _fetch_daily_df(ticker)
                if df is None or df.empty:
                    continue
                from positional.risk import check_reentry
                alert = check_reentry(ticker, df)
                if alert:
                    reentry_alerts_list.append({"ticker": ticker, "reason": alert})
                    ema21 = float(df["Close"].astype(float).ewm(span=21, adjust=False).mean().iloc[-1])
                    vol   = float(df["Volume"].iloc[-1])
                    avg_v = float(df["Volume"].tail(20).mean())
                    send_reentry_alert(ticker, float(df["Close"].iloc[-1]),
                                       ema21, vol / avg_v if avg_v > 0 else 1.0)
                    log.info("[pos_runner] RE-ENTRY: %s", alert)
            except Exception:
                pass
    except Exception as e:
        log.debug("[pos_runner] re-entry sweep failed: %s", e)

    summary = {
        "exited": exited,
        "sell_alerts": sell_alerts_list,
        "reentry_alerts": reentry_alerts_list,
        "updated": updated,
        "errors": errors,
    }
    log.info("[pos_runner] === EXIT CHECK END: exited=%d updated=%d errors=%d ===",
             exited, updated, errors)
    return summary


# ── EOD Scan ─────────────────────────────────────────────────────────────────

def run_eod_scan() -> dict:
    """
    Main EOD scan: runs Minervini Trend Template + VCP on the fundamental universe.
    Opens positions for BUY alerts (paper mode) or sends SELL/BUY alerts.
    Returns summary dict.
    """
    if not _positional_enabled():
        log.debug("[pos_runner] positional module disabled")
        return {"skipped": True, "reason": "positional_enabled=0"}
    if not _is_trading_day():
        return {"skipped": True, "reason": "non-trading day"}

    log.info("[pos_runner] === EOD SCAN START ===")

    # Step 1: Market regime
    from positional.market_regime import get_latest_regime
    regime = get_latest_regime()
    regime_flag  = regime.get("flag", "NEUTRAL")
    size_mult    = float(regime.get("size_multiplier", 0.70))

    if regime_flag == "DEFENSIVE":
        log.info("[pos_runner] Regime=DEFENSIVE — reduced position sizes (%.0f%%)",
                 size_mult * 100)

    # Step 2: Exit management first
    exit_result = run_exit_checks()
    sell_alerts = exit_result.get("sell_alerts", [])
    reentry_alerts = exit_result.get("reentry_alerts", [])

    # Step 3: Technical scan
    from positional.scanner import run_eod_scan as _scan
    scan_results = _scan()
    buy_alerts_scanned = [r for r in scan_results if r["alert_type"] == "BUY"]
    buy_alerts_taken: list[dict] = []

    for result in buy_alerts_scanned:
        ticker = result["ticker"]
        price  = result["price"]
        score  = result["score"]

        # Send Telegram alert for each BUY setup
        try:
            from positional.alerts import send_buy_alert
            send_buy_alert(result)
        except Exception:
            pass

        # Open position in paper mode (or real broker if configured)
        try:
            opened = _open_position(
                ticker=ticker,
                price=price,
                score=score,
                scan_id=0,  # scan_id looked up from pos_scans in real use
                regime_flag=regime_flag,
            )
            if opened:
                buy_alerts_taken.append(result)
        except Exception as e:
            log.warning("[pos_runner] open_position failed for %s: %s", ticker, e)

    # Step 4: Send EOD Telegram summary
    try:
        from positional.alerts import send_eod_summary
        time_stops = [s for s in sell_alerts if "TIME_STOP" in s.get("reason", "")]
        ema_exits  = [s for s in sell_alerts if "EMA_TRAIL" in s.get("reason", "")]
        hard_stops = [s for s in sell_alerts if "HARD_STOP" in s.get("reason", "")]
        send_eod_summary(
            regime=regime,
            buy_alerts=buy_alerts_scanned,
            sell_alerts=ema_exits + hard_stops,
            time_stops=time_stops,
            reentry_alerts=reentry_alerts,
        )
    except Exception as e:
        log.warning("[pos_runner] Telegram summary failed: %s", e)

    summary = {
        "regime": regime_flag,
        "buy_alerts": len(buy_alerts_scanned),
        "positions_opened": len(buy_alerts_taken),
        "positions_exited": exit_result.get("exited", 0),
        "reentry_alerts": len(reentry_alerts),
        "universe_size": len(scan_results),
    }
    log.info("[pos_runner] === EOD SCAN END: %s ===", summary)
    return summary


def run_regime_check() -> dict:
    """
    Monthly macro regime computation. Call on the 1st trading day of each month.
    Returns regime dict.
    """
    log.info("[pos_runner] === REGIME CHECK START ===")
    from positional.market_regime import compute_market_regime
    from positional.alerts import send_regime_alert
    regime = compute_market_regime()
    try:
        send_regime_alert(regime)
    except Exception:
        pass
    log.info("[pos_runner] === REGIME CHECK END: flag=%s ===", regime.get("flag"))
    return regime


# ── Daemon loop ────────────────────────────────────────────────────────────────

def run_positional_forever() -> None:
    """
    Background daemon thread: waits for scheduled scan times each day.
    Tracks per-date so a scan is never missed if the process wakes up late.
    Also runs a monthly regime check on the 1st trading day of the month.
    """
    log.info("[pos_runner] positional daemon started")
    _last_scan_date:   object = None
    _last_alert_date:  object = None
    _last_regime_month: object = None

    scan_h,  scan_m  = [int(x) for x in POSITIONAL_SCAN_TIME.split(":")]
    alert_h, alert_m = [int(x) for x in POSITIONAL_ALERT_TIME.split(":")]

    while True:
        try:
            now   = datetime.now(IST)
            today = now.date()
            past_scan  = (now.hour, now.minute) >= (scan_h,  scan_m)
            past_alert = (now.hour, now.minute) >= (alert_h, alert_m)

            # Monthly regime check (first trading day of month)
            if today.day <= 3 and today.weekday() < 5:
                if _last_regime_month != today.month:
                    _last_regime_month = today.month
                    try:
                        run_regime_check()
                    except Exception as e:
                        log.error("[pos_runner] regime check error: %s", e)

            # 4:00 PM: EOD scan
            if past_scan and _is_trading_day() and _last_scan_date != today:
                _last_scan_date = today
                try:
                    run_eod_scan()
                except Exception as e:
                    log.error("[pos_runner] EOD scan error: %s", e)
                time.sleep(30)
                continue

            time.sleep(30)
        except Exception as e:
            log.error("[pos_runner] daemon loop error: %s", e)
            time.sleep(60)

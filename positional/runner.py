"""
Positional trading runner.

Two entry points called from the main scheduler:
  run_positional_scan()      — pre-market (08:45 IST weekdays)
  run_positional_exit_check()— EOD management (15:20 IST weekdays)
  run_positional_forever()   — standalone daemon thread loop

Scan flow:
  1. Check bot_control.positional_enabled flag.
  2. Load positional universe from screener.
  3. Fetch 1d daily candles for each ticker.
  4. Run all 7 strategies, compute composite score.
  5. Write qualifying signals (score ≥ threshold) to pending_approvals
     with trade_type='positional'.
  6. Log signals to positional_signals table for analytics.

Exit flow:
  1. Load all OPEN positional positions.
  2. For each: fetch latest daily close, compute days_held.
  3. Check event guard (upcoming earnings).
  4. Evaluate stop/T1/trail/time/max-hold exits via risk.check_positional_exits().
  5. Execute exits (auto on DRY_RUN, queue approval on MANUAL).
  6. Update high_water_mark and days_held on surviving positions.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import List

from config import (
    DEFAULT_MODE,
    IST,
    INITIAL_CAPITAL,
    POSITIONAL_APPROVAL_TIMEOUT_MIN,
    POSITIONAL_CANDLE_INTERVAL,
    POSITIONAL_CAPITAL_PCT,
    POSITIONAL_EXIT_TIME,
    POSITIONAL_LOOKBACK_DAYS,
    POSITIONAL_MIN_COMPOSITE_SCORE,
    POSITIONAL_SCAN_TIME,
    POSITIONAL_T1_PARTIAL_PCT,
)
from data.fetcher import fetch_candles
from db.models import get_conn, insert_returning_id
from engine.paper_broker import execute as _intraday_execute
from positional.risk import (
    can_open_positional,
    check_event_guard,
    check_positional_exits,
    compute_atr_targets,
    compute_daily_atr,
    compute_delivery_costs,
    delivery_fill_price,
    get_positional_pool_cash,
    is_correlated_to_open_positions,
    positional_position_size,
)
from positional.scorer import evaluate_positional
from positional.screener import get_positional_universe
from positional.strategies import all_positional_strategies

log = logging.getLogger(__name__)


# ---------- Control helpers ----------

def _positional_enabled() -> bool:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT positional_enabled FROM bot_control WHERE id = 1"
            ).fetchone()
        return bool(row and row["positional_enabled"])
    except Exception:
        return False


def _bot_mode() -> str:
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT mode FROM bot_control WHERE id=1").fetchone()
        return (row["mode"] if row else DEFAULT_MODE).lower()
    except Exception:
        return DEFAULT_MODE


def _is_market_day() -> bool:
    from data.fetcher import market_is_open
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday / Sunday
        return False
    return True


# ---------- Signal persistence ----------

def _log_signal(ticker: str, strategy: str, action: str, score: float,
                price: float, reason: str, quality_score: float, meta: dict) -> None:
    ts = datetime.now(IST).isoformat()
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO positional_signals
                   (scanned_at, ticker, action, strategy, score, price,
                    reason, quality_score, taken, meta)
                   VALUES (?,?,?,?,?,?,?,?,0,?)""",
                (ts, ticker, action, strategy, score, price, reason,
                 quality_score, json.dumps(meta, default=str)),
            )
    except Exception as e:
        log.debug("positional_signals insert failed: %s", e)


def _queue_approval(
    ticker: str,
    action: str,
    qty: int,
    price: float,
    stop_loss: float,
    take_profit: float,
    strategy: str,
    score: float,
    reason: str,
) -> int:
    now = datetime.now(IST)
    expires = now + timedelta(minutes=POSITIONAL_APPROVAL_TIMEOUT_MIN)
    with get_conn() as conn:
        return insert_returning_id(
            conn,
            """INSERT INTO pending_approvals
               (created_at, expires_at, ticker, action, quantity, price,
                stop_loss, take_profit, strategy, composite_score, reason,
                status, trade_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,'pending','positional')""",
            (
                now.isoformat(), expires.isoformat(),
                ticker, action, qty, price,
                stop_loss, take_profit, strategy, score, reason,
            ),
        )


def _open_positional_position(
    ticker: str,
    price: float,
    qty: int,
    stop_loss: float,
    t1_target: float,
    tp_target: float,
    atr: float,
    strategy: str,
    score: float,
    quality_score: float,
    sector: str,
    strategy_breakdown: dict,
    conviction: str,
    hold_days: int,
) -> int:
    fill = delivery_fill_price("BUY", price)
    costs = compute_delivery_costs("BUY", fill, qty)
    ts = datetime.now(IST).isoformat()
    today = datetime.now(IST).date()
    expected_exit = (today + timedelta(days=hold_days)).isoformat()

    with get_conn() as conn:
        pos_id = insert_returning_id(
            conn,
            """INSERT INTO positions
               (ticker, entry_ts, entry_price, quantity, stop_loss, take_profit,
                strategy, composite_score, status, atr_at_entry, t1_target,
                t1_taken, high_water_mark, initial_quantity, side, trade_type)
               VALUES (?,?,?,?,?,?,?,?,'OPEN',?,?,0,?,?,?,?)""",
            (
                ticker, ts, fill, qty, stop_loss, tp_target,
                strategy, score, atr, t1_target,
                fill, qty, "LONG", "positional",
            ),
        )
        conn.execute(
            """INSERT INTO positional_positions
               (position_id, ticker, quality_score, conviction,
                expected_exit_date, hold_days_limit, days_held,
                sector, strategy_breakdown, created_at)
               VALUES (?,?,?,?,?,?,0,?,?,?)""",
            (
                pos_id, ticker, quality_score, conviction,
                expected_exit, hold_days, sector,
                json.dumps(strategy_breakdown, default=str), ts,
            ),
        )
        conn.execute(
            """INSERT INTO trades
               (ts, ticker, side, quantity, price, value, costs, net_value,
                strategy, reason, composite_score, mode, position_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ts, ticker, "BUY", qty, fill, fill * qty,
                costs, -(fill * qty + costs),
                strategy, f"positional open Q={quality_score:.0f}", score,
                "positional", pos_id,
            ),
        )
    log.info(
        "POSITIONAL OPEN: %s qty=%d fill=%.2f stop=%.2f T1=%.2f TP=%.2f "
        "ATR=%.2f strategy=%s score=%.1f",
        ticker, qty, fill, stop_loss, t1_target, tp_target, atr, strategy, score,
    )
    return pos_id


# ---------- Pre-market scan ----------

def run_positional_scan() -> dict:
    """Main pre-market scan. Returns summary dict."""
    if not _positional_enabled():
        log.debug("positional scan skipped — not enabled")
        return {"skipped": True, "reason": "positional_enabled=0"}

    if not _is_market_day():
        return {"skipped": True, "reason": "non-trading day"}

    log.info("=== POSITIONAL SCAN START ===")
    mode = _bot_mode()
    strategies = all_positional_strategies()
    universe = get_positional_universe()

    pool_cash = get_positional_pool_cash()
    queued, skipped_corr, skipped_risk, errors = 0, 0, 0, 0

    for ticker, quality_score, sector in universe:
        if not can_open_positional(pool_cash):
            log.info("positional: max positions reached or pool exhausted")
            break
        try:
            df = fetch_candles(ticker, interval=POSITIONAL_CANDLE_INTERVAL,
                               days=POSITIONAL_LOOKBACK_DAYS)
            if df is None or df.empty or len(df) < 60:
                skipped_risk += 1
                continue

            # Run all strategies
            signals = [s.generate(ticker, df, quality_score=quality_score)
                       for s in strategies]

            # Log all non-HOLD signals
            for sig in signals:
                if sig.action != "HOLD":
                    _log_signal(ticker, sig.strategy, sig.action, sig.score,
                                sig.price or 0.0, sig.reason, quality_score, sig.meta)

            decision = evaluate_positional(ticker, signals)

            if decision.action == "HOLD":
                continue

            if decision.composite_score < POSITIONAL_MIN_COMPOSITE_SCORE:
                continue

            # Risk checks
            if is_correlated_to_open_positions(ticker, df):
                skipped_corr += 1
                continue

            price = decision.price
            if not price:
                price = float(df["Close"].iloc[-1])

            atr = compute_daily_atr(df)
            if atr <= 0:
                skipped_risk += 1
                continue

            qty = positional_position_size(price, atr, pool_cash)
            if qty <= 0:
                skipped_risk += 1
                continue

            targets = compute_atr_targets(price, atr)
            strategy_label = f"positional:{decision.conviction}"
            breakdown = decision.strategy_scores

            if mode in ("auto", "dry_run"):
                _open_positional_position(
                    ticker=ticker,
                    price=price,
                    qty=qty,
                    stop_loss=targets["stop_loss"],
                    t1_target=targets["t1_target"],
                    tp_target=targets["tp_target"],
                    atr=atr,
                    strategy=strategy_label,
                    score=decision.composite_score,
                    quality_score=quality_score,
                    sector=sector,
                    strategy_breakdown=breakdown,
                    conviction=decision.conviction,
                    hold_days=decision.avg_hold_days,
                )
                pool_cash -= price * qty
            else:
                # MANUAL: queue approval
                _queue_approval(
                    ticker=ticker,
                    action=decision.action,
                    qty=qty,
                    price=price,
                    stop_loss=targets["stop_loss"],
                    take_profit=targets["tp_target"],
                    strategy=strategy_label,
                    score=decision.composite_score,
                    reason=(f"[Positional] {decision.top_reason} "
                            f"Q={quality_score:.0f} conv={decision.conviction}"),
                )
                pool_cash -= price * qty  # reserve cash optimistically

            queued += 1
            log.info(
                "POSITIONAL SIGNAL: %s %s score=%.1f conv=%s reason=%s",
                decision.action, ticker, decision.composite_score,
                decision.conviction, decision.top_reason[:80],
            )

        except Exception as e:
            log.warning("positional scan error for %s: %s", ticker, e)
            errors += 1

    summary = {"queued": queued, "skipped_corr": skipped_corr,
               "skipped_risk": skipped_risk, "errors": errors,
               "universe_size": len(universe)}
    log.info("=== POSITIONAL SCAN END: %s ===", summary)
    return summary


# ---------- EOD exit management ----------

def run_positional_exit_check() -> dict:
    """Check all open positional positions for exit conditions."""
    if not _is_market_day():
        return {"skipped": True}

    log.info("=== POSITIONAL EXIT CHECK START ===")
    mode = _bot_mode()
    today = datetime.now(IST).date()
    exited, t1_partial, updated, errors = 0, 0, 0, 0

    try:
        with get_conn() as conn:
            positions = conn.execute(
                """SELECT p.*, pp.days_held, pp.hold_days_limit, pp.id AS pp_id
                   FROM positions p
                   LEFT JOIN positional_positions pp ON pp.position_id = p.id
                   WHERE p.status = 'OPEN' AND p.trade_type = 'positional'"""
            ).fetchall()
        positions = [dict(r) for r in positions]
    except Exception as e:
        log.error("positional exit check: DB read failed: %s", e)
        return {"errors": 1}

    for pos in positions:
        ticker = pos["ticker"]
        pos_id = pos["id"]
        pp_id = pos.get("pp_id")

        try:
            df = fetch_candles(ticker, interval=POSITIONAL_CANDLE_INTERVAL,
                               days=10, use_cache=False)
            if df is None or df.empty:
                log.warning("positional exit: no data for %s", ticker)
                continue

            current_price = float(df["Close"].iloc[-1])
            days_held = int(pos.get("days_held") or 0)
            hwm = max(float(pos.get("high_water_mark") or current_price), current_price)

            # Update high water mark
            if current_price > float(pos.get("high_water_mark") or 0):
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE positions SET high_water_mark=? WHERE id=?",
                        (current_price, pos_id),
                    )

            # Event guard: exit before earnings/dividends
            event = check_event_guard(ticker)
            if event:
                _execute_positional_exit(
                    pos, current_price, mode,
                    reason=f"EVENT_GUARD: {event}",
                )
                exited += 1
                continue

            exit_reason = check_positional_exits(
                {**pos, "high_water_mark": hwm},
                current_price,
                days_held,
            )

            if exit_reason == "T1_PARTIAL":
                _execute_t1_partial(pos, current_price, mode)
                t1_partial += 1
            elif exit_reason is not None:
                _execute_positional_exit(pos, current_price, mode, reason=exit_reason)
                exited += 1
            else:
                # Update days_held
                if pp_id:
                    with get_conn() as conn:
                        conn.execute(
                            "UPDATE positional_positions SET days_held=? WHERE id=?",
                            (days_held + 1, pp_id),
                        )
                updated += 1

        except Exception as e:
            log.warning("positional exit error for %s: %s", ticker, e)
            errors += 1

    summary = {"exited": exited, "t1_partial": t1_partial,
               "updated": updated, "errors": errors}
    log.info("=== POSITIONAL EXIT CHECK END: %s ===", summary)
    return summary


def _execute_positional_exit(pos: dict, price: float, mode: str, reason: str) -> None:
    pos_id = pos["id"]
    ticker = pos["ticker"]
    qty = int(pos["quantity"])
    entry_price = float(pos["entry_price"])

    if qty <= 0:
        return

    fill = delivery_fill_price("SELL", price)
    costs = compute_delivery_costs("SELL", fill, qty)
    pnl = (fill - entry_price) * qty - costs
    pnl_pct = (fill - entry_price) / entry_price * 100
    ts = datetime.now(IST).isoformat()

    if mode == "manual":
        # Queue exit approval
        try:
            _queue_approval(
                ticker=ticker, action="SELL", qty=qty, price=fill,
                stop_loss=0.0, take_profit=0.0,
                strategy=pos.get("strategy", "positional"),
                score=float(pos.get("composite_score") or 50.0),
                reason=f"[Positional EXIT] {reason}",
            )
        except Exception as e:
            log.warning("positional exit approval queue failed for %s: %s", ticker, e)
        return

    try:
        with get_conn() as conn:
            conn.execute(
                """UPDATE positions SET status='CLOSED', exit_ts=?, exit_price=?,
                   pnl=?, pnl_pct=? WHERE id=?""",
                (ts, fill, round(pnl, 2), round(pnl_pct, 2), pos_id),
            )
            conn.execute(
                """INSERT INTO trades
                   (ts, ticker, side, quantity, price, value, costs, net_value,
                    strategy, reason, composite_score, mode, position_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts, ticker, "SELL", qty, fill, fill * qty,
                    costs, fill * qty - costs,
                    pos.get("strategy", "positional"), reason,
                    float(pos.get("composite_score") or 50.0),
                    "positional", pos_id,
                ),
            )
        log.info("POSITIONAL EXIT: %s qty=%d fill=%.2f pnl=%.2f (%.2f%%) %s",
                 ticker, qty, fill, pnl, pnl_pct, reason)
    except Exception as e:
        log.error("positional exit DB write failed for %s: %s", ticker, e)


def _execute_t1_partial(pos: dict, price: float, mode: str) -> None:
    pos_id = pos["id"]
    ticker = pos["ticker"]
    qty = int(pos["quantity"])
    t1_qty = max(1, int(qty * POSITIONAL_T1_PARTIAL_PCT))
    entry_price = float(pos["entry_price"])

    if t1_qty >= qty:
        _execute_positional_exit(pos, price, mode, reason="T1_FULL_EXIT")
        return

    fill = delivery_fill_price("SELL", price)
    costs = compute_delivery_costs("SELL", fill, t1_qty)
    partial_pnl = (fill - entry_price) * t1_qty - costs
    ts = datetime.now(IST).isoformat()

    if mode == "manual":
        _queue_approval(
            ticker=ticker, action="SELL", qty=t1_qty, price=fill,
            stop_loss=0.0, take_profit=0.0,
            strategy=pos.get("strategy", "positional"),
            score=float(pos.get("composite_score") or 50.0),
            reason=f"[Positional T1 PARTIAL] price reached T1 target",
        )
        return

    try:
        remaining = qty - t1_qty
        with get_conn() as conn:
            conn.execute(
                "UPDATE positions SET quantity=?, t1_taken=1 WHERE id=?",
                (remaining, pos_id),
            )
            conn.execute(
                """INSERT INTO trades
                   (ts, ticker, side, quantity, price, value, costs, net_value,
                    strategy, reason, composite_score, mode, position_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ts, ticker, "SELL", t1_qty, fill, fill * t1_qty,
                    costs, fill * t1_qty - costs,
                    pos.get("strategy", "positional"),
                    "T1_PARTIAL: first target hit",
                    float(pos.get("composite_score") or 50.0),
                    "positional", pos_id,
                ),
            )
        log.info("POSITIONAL T1 PARTIAL: %s sold %d @ %.2f pnl=%.2f remaining=%d",
                 ticker, t1_qty, fill, partial_pnl, remaining)
    except Exception as e:
        log.error("T1 partial DB write failed for %s: %s", ticker, e)


# ---------- Daemon loop ----------

def run_positional_forever() -> None:
    """Standalone daemon: waits for the scan and exit-check times each day.

    Uses >= comparison with per-date tracking so a scan is never missed if the
    machine was asleep at the exact scheduled minute and wakes up later.
    """
    log.info("positional runner started")
    _last_scan_date: object = None   # date object or None
    _last_exit_date: object = None

    while True:
        try:
            now = datetime.now(IST)
            today = now.date()
            hhmm = now.strftime("%H:%M")

            scan_h, scan_m = POSITIONAL_SCAN_TIME.split(":")
            exit_h, exit_m = POSITIONAL_EXIT_TIME.split(":")
            past_scan = (now.hour, now.minute) >= (int(scan_h), int(scan_m))
            past_exit = (now.hour, now.minute) >= (int(exit_h), int(exit_m))

            if past_scan and _last_scan_date != today:
                _last_scan_date = today
                run_positional_scan()
                time.sleep(60)
                continue

            if past_exit and _last_exit_date != today:
                _last_exit_date = today
                run_positional_exit_check()
                time.sleep(60)
                continue

            time.sleep(30)
        except Exception as e:
            log.error("positional runner loop error: %s", e)
            time.sleep(60)

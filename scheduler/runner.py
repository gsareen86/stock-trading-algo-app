"""
Main trading loop / scheduler.
- Polls bot_control table for status & mode.
- On each tick:
    1. refresh news + score sentiment
    2. fetch candles for the universe
    3. generate composite signals
    4. AUTO : execute approved signals
       MANUAL : enqueue for user approval
       DRY_RUN: log signals only, no trades
    5. evaluate stop-loss / take-profit / intraday square-off
    6. snapshot portfolio
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import List

from config import (
    APPROVAL_TIMEOUT_MIN,
    NEAR_CLOSE_POLL_INTERVAL_SEC,
    NEAR_CLOSE_START,
    NEWS_REFRESH_MIN,
    SIGNAL_POLL_INTERVAL_SEC,
    SQUARE_OFF_TIME,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    NO_TRADE_AFTER,
    NO_TRADE_BEFORE,
)
from data.fetcher import fetch_batch, latest_price, market_is_open
from data.news_scraper import scrape_all
from data.universe import load_universe
from db.models import get_conn, init_db, insert_returning_id
from engine.portfolio import (
    close_position,
    initialize_if_empty,
    is_open,
    open_position,
    open_positions,
    snapshot,
)
from engine.risk_manager import can_open_new, position_size
from nlp.sentiment import score_news_items
from scoring.composite import evaluate_batch, CompositeDecision

log = logging.getLogger(__name__)

# Module-level state for dashboard introspection
LAST_CYCLE: dict = {}
LAST_CYCLE_TS: datetime | None = None


# ---------- Bot control helpers ----------


def get_bot_state() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bot_control WHERE id=1").fetchone()
    return dict(row) if row else {"status": "STOPPED", "mode": "manual"}


def set_bot_state(status: str | None = None, mode: str | None = None) -> None:
    sets, args = [], []
    if status:
        sets.append("status=?")
        args.append(status)
    if mode:
        sets.append("mode=?")
        args.append(mode)
    sets.append("updated_at=?")
    args.append(datetime.utcnow().isoformat())
    if not sets:
        return
    with get_conn() as conn:
        conn.execute(f"UPDATE bot_control SET {', '.join(sets)} WHERE id=1", args)


# ---------- Approval queue ----------


def enqueue_approval(d: CompositeDecision, qty: int, sl: float, tp: float) -> int:
    now = datetime.utcnow()
    with get_conn() as conn:
        return insert_returning_id(
            conn,
            """INSERT INTO pending_approvals
               (created_at, expires_at, ticker, action, quantity, price,
                stop_loss, take_profit, strategy, composite_score, reason, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, 'PENDING')""",
            (
                now.isoformat(),
                (now + timedelta(minutes=APPROVAL_TIMEOUT_MIN)).isoformat(),
                d.ticker,
                d.action,
                qty,
                d.price,
                sl,
                tp,
                _top_strategy(d),
                d.composite_score,
                " | ".join(d.reasons),
            ),
        )


def expire_stale_approvals() -> int:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE pending_approvals
                  SET status='EXPIRED', decided_at=?, decision_note='auto-timeout'
                WHERE status='PENDING' AND expires_at < ?""",
            (now, now),
        )
        return cur.rowcount


def execute_single_approval(approval_id: int) -> int | None:
    """Execute a single APPROVED row immediately. Called from the dashboard
    when the user clicks Approve, so trades don't have to wait for the next
    scheduler cycle."""
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM pending_approvals WHERE id=? AND status='APPROVED'",
            (approval_id,),
        ).fetchone()
    if not r:
        return None
    if r["action"] != "BUY":
        return None
    pos_id = open_position(
        r["ticker"], r["price"], r["quantity"],
        stop_loss=r["stop_loss"], take_profit=r["take_profit"],
        strategy=r["strategy"], composite_score=r["composite_score"],
        reason=r["reason"] or "manual approval", mode="manual",
    )
    with get_conn() as conn:
        conn.execute(
            """UPDATE pending_approvals
                  SET status='EXECUTED',
                      decision_note=COALESCE(decision_note,'') || ' | pos_id='||?
                WHERE id=?""",
            (str(pos_id), approval_id),
        )
    return pos_id


def process_approved() -> int:
    """Execute all APPROVED rows in the queue (catch-up sweep)."""
    with get_conn() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM pending_approvals WHERE status='APPROVED'"
        ).fetchall()]
    executed = 0
    for i in ids:
        if execute_single_approval(i):
            executed += 1
    return executed


def _top_strategy(d: CompositeDecision) -> str:
    top = max(d.signals, key=lambda s: s.score if s.action == d.action else 0, default=None)
    return top.strategy if top else ""


# ---------- SL / TP / square-off ----------


def evaluate_exits(prices: dict) -> int:
    """
    Check every open position against its stop-loss, take-profit, and
    intraday square-off window. Returns count of positions closed.
    """
    closed = 0
    now_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%H:%M")
    squareoff_time = SQUARE_OFF_TIME

    for p in open_positions():
        ticker = p["ticker"]
        price = prices.get(ticker) or latest_price(ticker)
        if not price:
            continue
        reason = None
        if p["stop_loss"] and price <= p["stop_loss"]:
            reason = f"STOP-LOSS hit @ Rs.{price:.2f}"
        elif p["take_profit"] and price >= p["take_profit"]:
            reason = f"TAKE-PROFIT hit @ Rs.{price:.2f}"
        elif now_ist >= squareoff_time:
            # Show BOTH the policy cutoff and the actual execution time so the
            # log makes the lag (poll cadence) explicit instead of looking like
            # the cutoff itself was 15:30.
            reason = (
                f"INTRADAY square-off (cutoff {squareoff_time} IST, "
                f"executed {now_ist} IST)"
            )
        if reason:
            close_position(p["id"], price, reason=reason, mode="auto")
            closed += 1
    return closed


# ---------- Main cycle ----------


def run_cycle(universe: List[str] | None = None, *, force: bool = False) -> dict:
    """
    One iteration of the trading loop.
    Returns a dict describing what happened.

    `force=True` bypasses the RUNNING status check (used by the dashboard's
    'Run Cycle Now' button).
    """
    global LAST_CYCLE, LAST_CYCLE_TS
    init_db()
    initialize_if_empty()

    state = get_bot_state()
    if not force and state["status"] != "RUNNING":
        out = {"skipped": True, "reason": f"bot {state['status']}"}
        LAST_CYCLE, LAST_CYCLE_TS = out, datetime.utcnow()
        return out

    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    hhmm = now_ist.strftime("%H:%M")
    market_open = market_is_open(now_ist)

    # Refresh news + sentiment (throttled: every ~30 min)
    try:
        scrape_all()
        score_news_items()
    except Exception as e:
        log.warning("news refresh failed: %s", e)

    # Limit universe to keep runtime reasonable (random sample of 50 per cycle)
    uni = universe or load_universe()
    sample_size = min(50, len(uni))
    sampled = random.sample(uni, sample_size)

    # Always include currently open tickers so we can exit them
    open_tickers = [p["ticker"] for p in open_positions()]
    full = list(dict.fromkeys(open_tickers + sampled))

    candles = fetch_batch(full)
    prices = {t: float(df["Close"].iloc[-1]) for t, df in candles.items() if not df.empty}

    # 1. Evaluate exits
    closed = evaluate_exits(prices)

    # 2. Approval queue maintenance
    expired = expire_stale_approvals()
    executed = process_approved()

    # 3. Trade-hour / market-closed guards
    skip_entry_reason = None
    if not market_open:
        skip_entry_reason = "market closed"
    elif hhmm < NO_TRADE_BEFORE:
        skip_entry_reason = f"before {NO_TRADE_BEFORE} IST (volatility skip)"
    elif hhmm > NO_TRADE_AFTER:
        skip_entry_reason = f"after {NO_TRADE_AFTER} IST (no new entries)"

    signals_seen = 0
    buys_found = 0
    placed = 0
    enqueued = 0

    if not skip_entry_reason:
        decisions = evaluate_batch(candles)
        signals_seen = len(decisions)
        buys = [d for d in decisions if d.action == "BUY"]
        buys_found = len(buys)

        # Persist raw signals
        with get_conn() as conn:
            for d in decisions:
                conn.execute(
                    """INSERT INTO signals
                       (ts, ticker, action, strategy, technical_score, fundamental_score,
                        sentiment_score, composite_score, price, reason)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        datetime.utcnow().isoformat(),
                        d.ticker, d.action, _top_strategy(d),
                        d.technical_score, d.fundamental_score,
                        d.sentiment_score, d.composite_score,
                        d.price, " | ".join(d.reasons),
                    ),
                )

        # 4. Rank BUY candidates by composite and place/queue
        buys.sort(key=lambda d: d.composite_score, reverse=True)
        from engine.portfolio import get_cash
        cash = get_cash()
        open_count = len(open_positions())
        mode = state["mode"]

        for d in buys:
            if not can_open_new(open_count):
                break
            if is_open(d.ticker):
                continue
            qty = position_size(cash, d.price)
            if qty <= 0:
                continue
            sl = round(d.price * (1 - STOP_LOSS_PCT), 2)
            tp = round(d.price * (1 + TAKE_PROFIT_PCT), 2)

            if mode == "dry_run":
                continue
            elif mode == "auto":
                pos_id = open_position(
                    d.ticker, d.price, qty, stop_loss=sl, take_profit=tp,
                    strategy=_top_strategy(d), composite_score=d.composite_score,
                    reason=" | ".join(d.reasons[:3]), mode="auto",
                )
                if pos_id:
                    placed += 1
                    open_count += 1
                    cash -= d.price * qty
            elif mode == "manual":
                enqueue_approval(d, qty, sl, tp)
                enqueued += 1

    # Always snapshot so the chart moves even when no trades happen
    snapshot(prices)

    out = {
        "ts": datetime.utcnow().isoformat(),
        "market_open": market_open,
        "mode": state["mode"],
        "closed": closed, "expired": expired, "executed_approvals": executed,
        "signals": signals_seen, "buys_found": buys_found,
        "placed": placed, "enqueued": enqueued,
        "skipped_entry": skip_entry_reason,
        "universe_sampled": len(full),
        "prices_fetched": len(prices),
    }
    LAST_CYCLE, LAST_CYCLE_TS = out, datetime.utcnow()
    return out


def _next_poll_interval() -> int:
    """Use the tighter near-close cadence between NEAR_CLOSE_START and 15:30
    IST so intraday square-off fires within ≤NEAR_CLOSE_POLL_INTERVAL_SEC of
    the cutoff instead of the default 15-min lag."""
    now_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%H:%M")
    if NEAR_CLOSE_START <= now_ist <= "15:30":
        return NEAR_CLOSE_POLL_INTERVAL_SEC
    return SIGNAL_POLL_INTERVAL_SEC


def run_forever():
    """Poll-forever loop; blocks. Safe to ctrl-C."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.info(
        "Bot loop starting — default poll %ss, near-close (%s–15:30 IST) poll %ss",
        SIGNAL_POLL_INTERVAL_SEC, NEAR_CLOSE_START, NEAR_CLOSE_POLL_INTERVAL_SEC,
    )
    while True:
        try:
            # Always tick — run_cycle will internally skip based on status
            out = run_cycle()
            log.info("cycle: %s", out)
        except Exception:
            log.exception("cycle failed")
        time.sleep(_next_poll_interval())


def seconds_since_last_cycle() -> int | None:
    if LAST_CYCLE_TS is None:
        return None
    return int((datetime.utcnow() - LAST_CYCLE_TS).total_seconds())


if __name__ == "__main__":
    run_forever()

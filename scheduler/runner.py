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
from datetime import datetime, timedelta
from typing import List

from config import (
    APPROVAL_TIMEOUT_MIN,
    ATR_T1_PARTIAL_PCT,
    IST,
    MIN_COMPOSITE_SCORE,
    NEAR_CLOSE_POLL_INTERVAL_SEC,
    NEAR_CLOSE_START,
    NEWS_REFRESH_MIN,
    NO_TRADE_AFTER,
    NO_TRADE_BEFORE,
    NO_TRADE_WINDOWS,
    SIGNAL_POLL_INTERVAL_SEC,
    SQUARE_OFF_TIME,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    USE_ATR_EXITS,
    USE_NIFTY_TREND_FILTER,
)
from data.fetcher import fetch_batch, latest_price, market_is_open
from data.news_scraper import scrape_all
from data.universe import load_universe
from db.models import get_conn, init_db, insert_returning_id
from engine.atr_exits import (
    atr_targets,
    atr_targets_short,
    compute_atr,
    nifty_regime,
    nifty_trend_ok,  # kept for backwards-compat callers
    trail_stop_after_t1,
    trail_stop_after_t1_short,
)
from engine.paper_broker import execute as _broker_execute
from engine.portfolio import (
    close_position,
    initialize_if_empty,
    is_open,
    open_position,
    open_positions,
    partial_close_position,
    snapshot,
    update_position_levels,
)
from engine.risk_manager import can_open_new, position_size
from nlp.sentiment import score_news_items
from scoring.composite import evaluate_batch, CompositeDecision

log = logging.getLogger(__name__)

# Module-level state for dashboard introspection (per-process; the canonical
# cross-process source of truth is the ``cycle_log`` table — see
# ``last_cycle_summary`` below).
LAST_CYCLE: dict = {}
LAST_CYCLE_TS: datetime | None = None


# ---------- Cycle-log helpers (cross-process visibility) ----------


def _cycle_begin(triggered_by: str) -> int:
    """Insert a cycle_log row in RUNNING state and return its id.

    Why: the scheduler usually runs in a separate process from the Streamlit
    dashboard, so module-level ``LAST_CYCLE`` is invisible to the UI. Writing
    to a DB table makes the scheduler's progress observable everywhere.
    """
    started = datetime.utcnow().isoformat()
    try:
        with get_conn() as conn:
            return insert_returning_id(
                conn,
                """INSERT INTO cycle_log (started_at, status, triggered_by, summary)
                   VALUES (?, 'RUNNING', ?, NULL)""",
                (started, triggered_by),
            )
    except Exception as e:
        log.warning("cycle_log insert failed: %s", e)
        return -1


def _cycle_end(cycle_id: int, status: str, summary: dict) -> None:
    """Mark a cycle_log row finished with status DONE / ERROR / SKIPPED."""
    if cycle_id is None or cycle_id < 0:
        return
    try:
        import json
        with get_conn() as conn:
            conn.execute(
                """UPDATE cycle_log
                      SET finished_at=?, status=?, summary=?
                    WHERE id=?""",
                (datetime.utcnow().isoformat(), status,
                 json.dumps(summary, default=str), cycle_id),
            )
    except Exception as e:
        log.warning("cycle_log update failed: %s", e)


def last_cycle_summary() -> dict | None:
    """Return the most recent cycle_log row (any status) as a dict, or None."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM cycle_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


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


def enqueue_approval(d: CompositeDecision, qty: int, sl: float, tp: float,
                     side: str = "LONG") -> int:
    now = datetime.utcnow()
    with get_conn() as conn:
        return insert_returning_id(
            conn,
            """INSERT INTO pending_approvals
               (created_at, expires_at, ticker, action, quantity, price,
                stop_loss, take_profit, strategy, composite_score, reason, status, side)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, 'PENDING', ?)""",
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
                side,
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
    scheduler cycle.

    Race-condition guard: we first atomically transition APPROVED→EXECUTING.
    If rowcount==0 a concurrent caller already claimed it — we bail out.
    This prevents duplicate trades when the dashboard and a catch-up sweep
    run concurrently. If the process crashes between EXECUTING and EXECUTED
    the row is left in EXECUTING; a future manual retry or restart is needed.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE pending_approvals SET status='EXECUTING' WHERE id=? AND status='APPROVED'",
            (approval_id,),
        )
        if cur.rowcount != 1:
            return None
        r = conn.execute(
            "SELECT * FROM pending_approvals WHERE id=?",
            (approval_id,),
        ).fetchone()

    if not r or r["action"] not in ("BUY", "SELL"):
        with get_conn() as conn:
            conn.execute(
                "UPDATE pending_approvals SET status='APPROVED' WHERE id=? AND status='EXECUTING'",
                (approval_id,),
            )
        return None

    side = (r.get("side") or "LONG").upper()
    pos_id = open_position(
        r["ticker"], r["price"], r["quantity"],
        stop_loss=r["stop_loss"], take_profit=r["take_profit"],
        strategy=r["strategy"], composite_score=r["composite_score"],
        reason=r["reason"] or "manual approval", mode="manual",
        side=side,
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


def evaluate_exits(prices: dict) -> dict:
    """Check every open LONG / SHORT against its stops, T1, TP, square-off.

    For SHORTs every comparison is mirrored:
        stop_loss > entry, take_profit < entry, t1_target < entry,
        "high_water_mark" overloads as low_water_mark.
    Trailing-stop ratchets DOWN for shorts (lower is better).

    Returns ``{"closed": N, "t1_partials": M, "trailed": K}``.
    """
    counts = {"closed": 0, "t1_partials": 0, "trailed": 0}
    now_ist = datetime.now(IST).strftime("%H:%M")
    squareoff_time = SQUARE_OFF_TIME

    for p in open_positions():
        # Positional positions have their own dedicated daily exit-management
        # logic (positional.runner.run_positional_exit_check). Skip them here
        # so the intraday squareoff cutoff and intraday SL/TP/trail logic
        # don't accidentally close a multi-day positional hold.
        if (p.get("trade_type") or "intraday") == "positional":
            continue

        ticker = p["ticker"]
        price = prices.get(ticker) or latest_price(ticker)
        if not price:
            continue

        atr = p.get("atr_at_entry")
        t1_target = p.get("t1_target")
        t1_taken = bool(p.get("t1_taken") or 0)
        side = (p.get("side") or "LONG").upper()
        wm = p.get("high_water_mark") or p["entry_price"]
        entry = float(p["entry_price"])

        # ----- (1) Update water-mark BEFORE any exit decision -----
        # LONG : track HIGHEST price seen (high-water mark).
        # SHORT: track LOWEST price seen (low-water mark) — same column.
        if side == "LONG":
            new_wm = max(float(wm), float(price))
        else:
            new_wm = min(float(wm), float(price))

        # ----- (4) T1 partial -----
        t1_hit = (
            USE_ATR_EXITS and t1_target and not t1_taken and atr
            and ((side == "LONG"  and price >= float(t1_target))
                 or (side == "SHORT" and price <= float(t1_target)))
        )
        if t1_hit:
            qty_to_book = max(1, int(p["quantity"] * ATR_T1_PARTIAL_PCT))
            if qty_to_book >= p["quantity"]:
                log.debug(
                    "T1 partial skipped for %s pos %d: qty_to_book=%d >= remaining=%d "
                    "(ATR_T1_PARTIAL_PCT=%.2f). Will close fully on TP/SL.",
                    ticker, p["id"], qty_to_book, p["quantity"], ATR_T1_PARTIAL_PCT,
                )
            if qty_to_book < p["quantity"]:
                pnl = partial_close_position(
                    p["id"], price, qty_to_book,
                    reason=(
                        f"T1 partial ({side}) @ Rs.{price:.2f} "
                        f"(entry {entry:.2f}, ATR {atr:.2f})"
                    ),
                    mode="auto",
                )
                if pnl is not None:
                    counts["t1_partials"] += 1
                    # Move stop to break-even = entry. For LONG that's UP
                    # (max with current stop); for SHORT it's DOWN (min).
                    cur_stop = float(p["stop_loss"] or 0)
                    if side == "LONG":
                        new_stop = max(cur_stop, entry)
                    else:
                        new_stop = min(cur_stop, entry) if cur_stop else entry
                    update_position_levels(
                        p["id"],
                        stop_loss=round(new_stop, 2),
                        high_water_mark=round(new_wm, 2),
                    )
                    continue

        # ----- (5) Trailing stop — only after T1 -----
        new_stop_for_trail = None
        if USE_ATR_EXITS and t1_taken and atr:
            cur_stop = float(p["stop_loss"] or 0)
            if side == "LONG":
                candidate = trail_stop_after_t1(new_wm, float(atr))
                if candidate > cur_stop:           # ratchet up
                    new_stop_for_trail = candidate
                    counts["trailed"] += 1
            else:
                candidate = trail_stop_after_t1_short(new_wm, float(atr))
                # Validate: candidate must be above current price (still a
                # valid stop) and above entry (short entered below candidate).
                candidate_valid = candidate > float(price)
                if candidate_valid and (cur_stop == 0 or candidate < cur_stop):
                    new_stop_for_trail = candidate
                    counts["trailed"] += 1

        # Persist WM + trailed stop (if any) before exit-check.
        update_kwargs = {}
        if new_wm != float(wm):
            update_kwargs["high_water_mark"] = round(new_wm, 2)
        if new_stop_for_trail is not None:
            update_kwargs["stop_loss"] = new_stop_for_trail
        if update_kwargs:
            update_position_levels(p["id"], **update_kwargs)

        effective_stop = (
            new_stop_for_trail
            if new_stop_for_trail is not None
            else (p["stop_loss"] or 0)
        )
        reason = None
        # SL hit:  LONG = price <= stop, SHORT = price >= stop.
        if effective_stop:
            stop_hit = (
                (side == "LONG"  and price <= float(effective_stop))
                or (side == "SHORT" and price >= float(effective_stop))
            )
            if stop_hit:
                tag = "TRAILING-STOP" if t1_taken else "STOP-LOSS"
                reason = (
                    f"{tag} ({side}) hit @ Rs.{price:.2f} "
                    f"(stop Rs.{effective_stop:.2f})"
                )
        # TP hit: LONG = price >= tp, SHORT = price <= tp.
        if not reason and p["take_profit"]:
            tp_hit = (
                (side == "LONG"  and price >= float(p["take_profit"]))
                or (side == "SHORT" and price <= float(p["take_profit"]))
            )
            if tp_hit:
                reason = f"TAKE-PROFIT ({side}) hit @ Rs.{price:.2f}"
        if not reason and now_ist >= squareoff_time:
            reason = (
                f"INTRADAY square-off (cutoff {squareoff_time} IST, "
                f"executed {now_ist} IST)"
            )
        if reason:
            close_position(p["id"], price, reason=reason, mode="auto")
            counts["closed"] += 1
    return counts


# ---------- Main cycle ----------


def run_cycle(universe: List[str] | None = None, *, force: bool = False,
              triggered_by: str = "scheduler") -> dict:
    """
    One iteration of the trading loop.
    Returns a dict describing what happened.

    `force=True` bypasses the RUNNING status check (used by the dashboard's
    'Run Cycle Now' button).
    `triggered_by` is logged in cycle_log for cross-process visibility.
    """
    global LAST_CYCLE, LAST_CYCLE_TS
    # init_db() is called ONCE at process startup (main.py). Calling it here
    # every cycle was unnecessary and caused the entire cycle to crash whenever
    # the Postgres connection timed out (e.g. laptop sleep / IPv6 DNS failure).
    initialize_if_empty()

    cycle_id = _cycle_begin(triggered_by)

    state = get_bot_state()
    if not force and state["status"] != "RUNNING":
        out = {"skipped": True, "reason": f"bot {state['status']}"}
        LAST_CYCLE, LAST_CYCLE_TS = out, datetime.utcnow()
        _cycle_end(cycle_id, "SKIPPED", out)
        return out

    try:
        cycle_start_ist = datetime.now(IST)
        market_open = market_is_open(cycle_start_ist)

        # Short-circuit when the market is closed. Fetching news + candles for
        # 50 tickers and running every strategy on stale data wastes ~20-30 s
        # per cycle and produces no actionable signals (no entries/exits are
        # possible while NSE is shut). We only run light bookkeeping —
        # expire stale approvals — and return.
        if not market_open:
            try:
                expired = expire_stale_approvals()
            except Exception as e:
                log.warning("expire_stale_approvals failed: %s", e)
                expired = 0
            out = {
                "ts": datetime.utcnow().isoformat(),
                "market_open": False,
                "skipped": True,
                "reason": "market closed",
                "expired": expired,
            }
            LAST_CYCLE, LAST_CYCLE_TS = out, datetime.utcnow()
            _cycle_end(cycle_id, "SKIPPED", out)
            return out

        # Refresh news + sentiment (throttled: every ~30 min)
        try:
            scrape_all()
            score_news_items()
        except Exception as e:
            log.warning("news refresh failed: %s", e)

        # Limit universe to keep runtime reasonable. Sample size is a runtime
        # knob so you can scale up to 100 / 500 without code edits — see
        # CYCLE_SAMPLE_SIZE in config.py and the dashboard's Runtime
        # Parameters panel.
        from config import CYCLE_SAMPLE_SIZE
        uni = universe or load_universe()
        sample_size = min(CYCLE_SAMPLE_SIZE, len(uni))
        sampled = random.sample(uni, sample_size)

        # Always include currently open tickers so we can exit them
        open_tickers = [p["ticker"] for p in open_positions()]
        full = list(dict.fromkeys(open_tickers + sampled))

        candles = fetch_batch(full)
        prices = {t: float(df["Close"].iloc[-1]) for t, df in candles.items() if not df.empty}

        # 1. Evaluate exits — now returns a dict (see evaluate_exits docstring)
        exit_counts = evaluate_exits(prices)
        closed = exit_counts["closed"]
        t1_partials = exit_counts["t1_partials"]
        trailed = exit_counts["trailed"]

        # 2. Approval queue maintenance
        expired = expire_stale_approvals()
        executed = process_approved()

        # 3. Trade-hour / market-closed guards.
        # IMPORTANT: re-read the clock HERE, not at the top of the cycle. News
        # scraping + 50-ticker yfinance fetch can take 1-3 minutes, so a cycle
        # that started at 09:29 IST might reach this gate at 09:31 — using the
        # stale start time was incorrectly skipping cycles past the cutoff.
        now_ist = datetime.now(IST)
        hhmm = now_ist.strftime("%H:%M")
        skip_entry_reason = None
        if not market_open:
            skip_entry_reason = "market closed"
        elif hhmm < NO_TRADE_BEFORE:
            skip_entry_reason = f"before {NO_TRADE_BEFORE} IST (volatility skip)"
        elif hhmm > NO_TRADE_AFTER:
            skip_entry_reason = f"after {NO_TRADE_AFTER} IST (no new entries)"
        else:
            # Block entries inside any configured "dead zone" window. Existing
            # positions are still exit-managed above; only NEW entries are gated.
            for win_start, win_end in NO_TRADE_WINDOWS:
                if win_start <= hhmm <= win_end:
                    skip_entry_reason = (
                        f"within no-trade window {win_start}-{win_end} IST"
                    )
                    break

        # ----- Market-regime gate (3-way: bullish / bearish / neutral) -----
        # Routes signals based on regime so the bot can profit in BOTH
        # directions:
        #   bullish  → take only LONGs   from BUY  signals
        #   bearish  → take only SHORTs  from SELL signals
        #   neutral  → take BOTH (mean-reversion sweet spot)
        regime, trend_reason = ("neutral", "trend filter disabled")
        if USE_NIFTY_TREND_FILTER:
            try:
                regime, trend_reason = nifty_regime()
            except Exception as e:
                log.warning("nifty_regime crashed: %s", e)
                regime, trend_reason = "neutral", f"regime error: {e}"

        signals_seen = 0
        buys_found = 0
        sells_found = 0
        placed = 0
        placed_short = 0
        enqueued = 0
        atr_skipped = 0

        allow_long  = (regime in ("bullish", "neutral"))
        allow_short = (regime in ("bearish", "neutral"))

        # Always evaluate and log signals so the Signal History panel shows
        # what was generated even during no-trade windows and STOPPED state.
        decisions = evaluate_batch(candles)
        signals_seen = len(decisions)
        buys  = [d for d in decisions if d.action == "BUY"]
        sells = [d for d in decisions if d.action == "SELL"]
        buys_found  = len(buys)
        sells_found = len(sells)

        # Persist raw signals regardless of no-trade window or bot status.
        # threshold_at_time and mode_at_time let the dashboard badge each signal
        # against the threshold/mode that was ACTIVE when the signal fired —
        # not the current live settings (which the user may have changed since).
        _threshold_now = float(state.get("min_composite_score", MIN_COMPOSITE_SCORE))
        _mode_now = state.get("mode", "manual")
        with get_conn() as conn:
            for d in decisions:
                conn.execute(
                    """INSERT INTO signals
                       (ts, ticker, action, strategy, technical_score, fundamental_score,
                        sentiment_score, composite_score, price, reason,
                        threshold_at_time, mode_at_time)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        datetime.utcnow().isoformat(),
                        d.ticker, d.action, _top_strategy(d),
                        d.technical_score, d.fundamental_score,
                        d.sentiment_score, d.composite_score,
                        d.price, " | ".join(d.reasons),
                        _threshold_now, _mode_now,
                    ),
                )

        if not skip_entry_reason:

            from engine.portfolio import get_cash
            cash = get_cash()
            open_count = len(open_positions())
            mode = state["mode"]

            # Build a unified, regime-filtered, score-sorted entry queue.
            entry_queue: list[tuple[CompositeDecision, str]] = []
            if allow_long:
                for d in sorted(buys, key=lambda x: x.composite_score, reverse=True):
                    entry_queue.append((d, "LONG"))
            if allow_short:
                for d in sorted(sells, key=lambda x: x.composite_score, reverse=True):
                    entry_queue.append((d, "SHORT"))
            # Re-sort overall by composite so the strongest signal (long OR
            # short) wins the next slot.
            entry_queue.sort(key=lambda t: t[0].composite_score, reverse=True)

            for d, side in entry_queue:
                if not can_open_new(open_count):
                    break
                if is_open(d.ticker):
                    continue
                qty = position_size(cash, d.price)
                if qty <= 0:
                    continue

                # ----- Compute side-aware ATR exit levels -----
                sl = tp = t1 = atr_used = None
                df_for_atr = candles.get(d.ticker)
                if USE_ATR_EXITS and df_for_atr is not None:
                    atr_value = compute_atr(df_for_atr)
                    if atr_value:
                        targets = (
                            atr_targets_short(d.price, atr_value)
                            if side == "SHORT"
                            else atr_targets(d.price, atr_value)
                        )
                    else:
                        targets = {"ok": False}
                    if targets.get("ok"):
                        sl = targets["stop_loss"]
                        tp = targets["take_profit"]
                        t1 = targets["t1_target"]
                        atr_used = targets["atr"]
                    else:
                        atr_skipped += 1
                if sl is None:
                    # Legacy fixed-pct fallback. For SHORT the signs flip.
                    if side == "SHORT":
                        sl = round(d.price * (1 + STOP_LOSS_PCT), 2)
                        tp = round(d.price * (1 - TAKE_PROFIT_PCT), 2)
                    else:
                        sl = round(d.price * (1 - STOP_LOSS_PCT), 2)
                        tp = round(d.price * (1 + TAKE_PROFIT_PCT), 2)
                    t1 = None
                    atr_used = None

                if mode == "dry_run":
                    continue
                elif mode == "auto":
                    pos_id = open_position(
                        d.ticker, d.price, qty, stop_loss=sl, take_profit=tp,
                        strategy=_top_strategy(d), composite_score=d.composite_score,
                        reason=" | ".join(d.reasons[:3]), mode="auto",
                        atr_at_entry=atr_used, t1_target=t1, side=side,
                    )
                    if pos_id:
                        if side == "SHORT":
                            placed_short += 1
                        else:
                            placed += 1
                        open_count += 1
                        # Deduct the realistic cost (fill price + all fees)
                        # so subsequent signals in this cycle use accurate cash.
                        est = _broker_execute("BUY", d.price, qty)
                        cash += est.net  # est.net is negative on BUY-side
                elif mode == "manual":
                    # Both LONG and SHORT signals go to pending_approvals.
                    # The side column added to pending_approvals schema lets
                    # the dashboard render SHORT approvals correctly and
                    # execute_single_approval() can use it for the short path.
                    enqueue_approval(d, qty, sl, tp, side=side)
                    enqueued += 1

        # Always snapshot so the chart moves even when no trades happen
        snapshot(prices)

        out = {
            "ts": datetime.utcnow().isoformat(),
            "market_open": market_open,
            "mode": state["mode"],
            "regime": regime,
            "closed": closed, "expired": expired, "executed_approvals": executed,
            "t1_partials": t1_partials, "trailed": trailed,
            "signals": signals_seen,
            "buys_found": buys_found, "sells_found": sells_found,
            "placed_long": placed, "placed_short": placed_short,
            "enqueued": enqueued,
            "atr_skipped": atr_skipped,
            "skipped_entry": skip_entry_reason,
            "trend_filter": trend_reason,
            "universe_sampled": len(full),
            "prices_fetched": len(prices),
        }
        LAST_CYCLE, LAST_CYCLE_TS = out, datetime.utcnow()
        _cycle_end(cycle_id, "DONE", out)
        return out
    except Exception as e:
        log.exception("run_cycle failed")
        err = {"error": str(e), "ts": datetime.utcnow().isoformat()}
        LAST_CYCLE, LAST_CYCLE_TS = err, datetime.utcnow()
        _cycle_end(cycle_id, "ERROR", err)
        raise


def _next_poll_interval() -> int:
    """Adaptive poll cadence:
      - market closed → 30 min idle poll (no fetches, just status)
      - 15:00–15:30 IST → near-close cadence (5 min) so square-off fires fast
      - otherwise default 15 min poll matching the 15-min candle interval
    """
    now = datetime.now(IST)
    if not market_is_open(now):
        return 1800  # 30 min idle poll when market closed
    hhmm = now.strftime("%H:%M")
    if NEAR_CLOSE_START <= hhmm <= "15:30":
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

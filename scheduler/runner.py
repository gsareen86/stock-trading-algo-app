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
    ATR_T1_PARTIAL_PCT,
    NEAR_CLOSE_POLL_INTERVAL_SEC,
    NEAR_CLOSE_START,
    NEWS_REFRESH_MIN,
    SIGNAL_POLL_INTERVAL_SEC,
    SQUARE_OFF_TIME,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    NO_TRADE_AFTER,
    NO_TRADE_BEFORE,
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


def evaluate_exits(prices: dict) -> dict:
    """Check every open LONG / SHORT against its stops, T1, TP, square-off.

    For SHORTs every comparison is mirrored:
        stop_loss > entry, take_profit < entry, t1_target < entry,
        "high_water_mark" overloads as low_water_mark.
    Trailing-stop ratchets DOWN for shorts (lower is better).

    Returns ``{"closed": N, "t1_partials": M, "trailed": K}``.
    """
    counts = {"closed": 0, "t1_partials": 0, "trailed": 0}
    now_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%H:%M")
    squareoff_time = SQUARE_OFF_TIME

    for p in open_positions():
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
                if cur_stop == 0 or candidate < cur_stop:   # ratchet down
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
    init_db()
    initialize_if_empty()

    cycle_id = _cycle_begin(triggered_by)

    state = get_bot_state()
    if not force and state["status"] != "RUNNING":
        out = {"skipped": True, "reason": f"bot {state['status']}"}
        LAST_CYCLE, LAST_CYCLE_TS = out, datetime.utcnow()
        _cycle_end(cycle_id, "SKIPPED", out)
        return out

    try:
        cycle_start_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        market_open = market_is_open(cycle_start_ist)

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
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        hhmm = now_ist.strftime("%H:%M")
        skip_entry_reason = None
        if not market_open:
            skip_entry_reason = "market closed"
        elif hhmm < NO_TRADE_BEFORE:
            skip_entry_reason = f"before {NO_TRADE_BEFORE} IST (volatility skip)"
        elif hhmm > NO_TRADE_AFTER:
            skip_entry_reason = f"after {NO_TRADE_AFTER} IST (no new entries)"

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

        if not skip_entry_reason:
            decisions = evaluate_batch(candles)
            signals_seen = len(decisions)
            buys  = [d for d in decisions if d.action == "BUY"]
            sells = [d for d in decisions if d.action == "SELL"]
            buys_found  = len(buys)
            sells_found = len(sells)

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
                        cash -= d.price * qty   # margin block, both sides
                elif mode == "manual":
                    # Manual approvals stay long-only for now (queue schema
                    # doesn't carry side). SHORT signals in manual mode are
                    # surfaced in the signal log but not enqueued.
                    if side == "LONG":
                        enqueue_approval(d, qty, sl, tp)
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

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
from typing import Optional

from config import (
    DEFAULT_MODE,
    IST,
    POSITIONAL_ALERT_TIME,
    POSITIONAL_RESEARCH_REFRESH_TIME,
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
        import yfinance as yf
        import pandas as pd
        t = ticker if ticker.endswith((".NS", ".BO")) else ticker + ".NS"
        df = yf.download(t, period="14mo", interval="1d",
                         auto_adjust=True, progress=False)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex) or hasattr(df.columns, "levels"):
                if any(t in str(col) for col in df.columns.get_level_values(0)):
                    df = df[t]
                else:
                    df.columns = df.columns.get_level_values(0)
            return df
        return None
    except Exception as e:
        log.debug("[pos_runner] fetch failed for %s: %s", ticker, e)
        return None


def _microcap_exposure() -> float:
    """Current ₹ value of open swing positions in the microcap tier."""
    from data.hygiene import is_microcap
    from db.models import get_conn
    total = 0.0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, entry_price, quantity FROM pos_positions WHERE status='OPEN'"
        ).fetchall()
    for r in rows:
        try:
            if is_microcap(r["ticker"]):
                total += float(r["entry_price"]) * int(r["quantity"])
        except Exception:
            continue
    return total


# ── Open a new position ───────────────────────────────────────────────────────

def _open_position(ticker: str, price: float, score: float,
                   scan_id: int, regime_flag: str,
                   reason: Optional[str] = None,
                   reduce_size: bool = False,
                   est_hold_days: Optional[int] = None) -> bool:
    """Place a BUY order and record in pos_positions + pos_trades."""
    from positional.risk import (
        positional_position_size, positional_position_size_risk,
        compute_hard_stop, compute_target,
        compute_delivery_costs, delivery_fill_price,
        get_positional_cash, can_open_position,
    )
    from positional.market_regime import current_size_multiplier
    from positional.broker import get_broker
    from db.models import get_conn, insert_returning_id

    if not can_open_position():
        log.info("[pos_runner] %s: max positions reached or no cash", ticker)
        return False

    # Deterministic event guard — no entry within N days of a known results /
    # ex-date (NSE calendar). Fail-open: empty calendar never blocks.
    from config import POSITIONAL_EVENT_GUARD_ENABLED, POSITIONAL_EVENT_GUARD_DAYS
    if POSITIONAL_EVENT_GUARD_ENABLED:
        try:
            from data.nse_calendar import has_blocking_event
            block = has_blocking_event(ticker, days=POSITIONAL_EVENT_GUARD_DAYS)
            if block:
                log.info("[pos_runner] %s: entry blocked by event guard — %s", ticker, block)
                return False
        except Exception as e:
            log.debug("[pos_runner] event guard check failed for %s: %s", ticker, e)

    # Stage-0 hygiene gate — known ASM/GSM listing, poor liquidity for the
    # swing book, or a failed microcap integrity check blocks the entry;
    # missing data never does.
    microcap = False
    adv_cr = None
    try:
        from data.hygiene import hygiene_check
        hc = hygiene_check(ticker, book="swing")
        if not hc["passed"]:
            log.info("[pos_runner] %s: entry blocked by hygiene gate — %s",
                     ticker, "; ".join(hc["reasons"]))
            return False
        microcap = bool(hc.get("microcap"))
        adv_cr = hc.get("median_traded_value_cr")
    except Exception as e:
        log.debug("[pos_runner] hygiene check failed for %s: %s", ticker, e)

    # Microcap exposure budget: the tier as a whole may not exceed
    # MICROCAP_MAX_BOOK_PCT of the pool — upside of the tier without
    # letting it become the book.
    if microcap:
        from config import MICROCAP_MAX_BOOK_PCT, POSITIONAL_CAPITAL
        try:
            exposure = _microcap_exposure()
            if exposure >= POSITIONAL_CAPITAL * MICROCAP_MAX_BOOK_PCT:
                log.info("[pos_runner] %s: microcap budget full "
                         "(₹%.0f ≥ %.0f%% of pool) — entry skipped",
                         ticker, exposure, MICROCAP_MAX_BOOK_PCT * 100)
                return False
        except Exception as e:
            log.debug("[pos_runner] microcap budget check failed: %s", e)

    size_mult = current_size_multiplier()
    if reduce_size:
        size_mult *= 0.50
    if microcap:
        from config import MICROCAP_RISK_MULT
        size_mult *= MICROCAP_RISK_MULT   # halve per-trade risk in the tier

    from config import POSITIONAL_USE_RISK_SIZING
    if POSITIONAL_USE_RISK_SIZING:
        # Risk-based sizing: rupee risk to the hard stop, capped vs the
        # stock's daily traded value (never > 1.5% of ADV).
        stop_est = compute_hard_stop(price)
        qty = positional_position_size_risk(
            price, stop_est, size_multiplier=size_mult,
            cash_available=get_positional_cash(),
            adv_cr=adv_cr,
        )
    else:
        qty = positional_position_size(price, size_multiplier=size_mult)
    if qty <= 0:
        log.info("[pos_runner] %s: qty=0 at price=%.2f (insufficient capital)", ticker, price)
        return False

    # Pre-trade LLM Veto Gate
    from config import LLM_ENABLE_VETO
    if LLM_ENABLE_VETO and reason is None:
        try:
            from llm.veto import llm_veto, apply_veto_to_qty
            # Fetch recent news and metadata for the ticker
            with get_conn() as conn:
                _recent_news = [
                    dict(r) for r in conn.execute(
                        """SELECT title, ts, sentiment FROM news
                           WHERE (',' || tickers || ',') LIKE ? ORDER BY ts DESC LIMIT 5""",
                        (f"%,{ticker.upper()},%",),
                    ).fetchall()
                ]
                row_sector = conn.execute(
                    "SELECT sector FROM fundamentals WHERE ticker=?",
                    (ticker,),
                ).fetchone()
                sector = row_sector["sector"] if row_sector and row_sector["sector"] else ""

            sentiments = [float(n["sentiment"]) for n in _recent_news if n.get("sentiment") is not None]
            sentiment_score = sum(sentiments) / len(sentiments) if sentiments else 0.0

            _fired = [("Minervini Trend Template & VCP", "BUY", score)]
            
            _verdict, _vreason = llm_veto(
                ticker=ticker,
                side="LONG",
                price=price,
                composite_score=score,
                technical_score=score,
                sentiment_score=sentiment_score,
                fired_strategies=_fired,
                regime=regime_flag.lower(),
                recent_news=_recent_news,
                sector=sector,
            )
            
            qty = apply_veto_to_qty(qty, _verdict)
            if qty == 0:
                log.info("[pos_runner] LLM veto SKIP LONG %s: %s", ticker, _vreason)
                return False
            if _verdict == "REDUCE":
                log.info("[pos_runner] LLM veto REDUCE LONG %s (50%%): %s", ticker, _vreason)
                reason = f"LLM VETO REDUCE (50%): {_vreason}"
            else:
                reason = f"LLM VETO PROCEED: {_vreason}"
        except Exception as e:
            log.warning("[pos_runner] LLM veto failed for %s: %s", ticker, e)

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

    entry_reason = reason or f"EOD scan entry score={score:.0f}"

    try:
        with get_conn() as conn:
            pos_id = insert_returning_id(
                conn,
                """INSERT INTO pos_positions
                   (ticker, entry_date, entry_price, quantity, hard_stop,
                    ema_trail_stop, target_price, status, peak_price,
                    below_ema_consecutive, days_held, regime_at_entry, scan_id,
                    initial_quantity, partial_taken, time_stop_days)
                   VALUES (?,?,?,?,?,?,?,?,?,0,0,?,?,?,0,?)""",
                (ticker, entry_date, fill, qty, hard_stop,
                 None, target, "OPEN", fill, regime_flag, scan_id,
                 qty, est_hold_days),
            )
            conn.execute(
                """INSERT INTO pos_trades
                   (ts, ticker, side, quantity, price, costs, pnl, reason, position_id)
                   VALUES (?,?,?,?,?,?,0,?,?)""",
                (entry_date, ticker, "BUY", qty, fill, costs,
                 entry_reason, pos_id),
            )
    except Exception as e:
        log.error("[pos_runner] DB write failed for %s: %s", ticker, e)
        return False

    log.info("[pos_runner] OPENED: %s qty=%d fill=%.2f stop=%.2f target=%.2f broker=%s reason=%s",
             ticker, qty, fill, hard_stop, target, broker.name, entry_reason)
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


# ── Partial de-risk (+2R) ─────────────────────────────────────────────────────

def _partial_close_position(pos: dict, current_price: float) -> bool:
    """Sell POSITIONAL_PARTIAL_FRACTION of the position at +R-multiple and
    move the hard stop to breakeven. Mutates ``pos`` (quantity, partial_taken,
    hard_stop) so the caller's subsequent exit checks see the new state."""
    from config import POSITIONAL_PARTIAL_FRACTION
    from positional.risk import compute_delivery_costs
    from positional.broker import get_broker
    from db.models import get_conn, insert_returning_id

    pos_id = pos["id"]
    ticker = pos["ticker"]
    qty    = int(pos["quantity"])
    entry  = float(pos["entry_price"])

    sell_qty = int(qty * POSITIONAL_PARTIAL_FRACTION)
    if sell_qty <= 0 or sell_qty >= qty:
        return False

    broker = get_broker()
    result = broker.place_order(ticker, "SELL", sell_qty, current_price)
    fill   = result.fill_price if result.success else current_price

    costs   = compute_delivery_costs("SELL", fill, sell_qty)
    pnl     = (fill - entry) * sell_qty - costs
    ts      = datetime.now(IST).isoformat()
    new_qty = qty - sell_qty
    reason  = (f"PARTIAL_2R: sold {sell_qty}/{qty} at {fill:.2f} "
               f"(+{(fill - entry) / entry * 100:.1f}%), stop moved to breakeven")

    try:
        with get_conn() as conn:
            conn.execute(
                """UPDATE pos_positions
                   SET quantity=?, partial_taken=1, hard_stop=?
                   WHERE id=?""",
                (new_qty, round(entry, 2), pos_id),
            )
            insert_returning_id(
                conn,
                """INSERT INTO pos_trades
                   (ts, ticker, side, quantity, price, costs, pnl, reason, position_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ts, ticker, "SELL", sell_qty, fill, costs, round(pnl, 2), reason, pos_id),
            )
    except Exception as e:
        log.error("[pos_runner] partial close DB write failed for %s: %s", ticker, e)
        return False

    pos["quantity"] = new_qty
    pos["partial_taken"] = 1
    pos["hard_stop"] = round(entry, 2)
    log.info("[pos_runner] PARTIAL: %s %s", ticker, reason)
    try:
        from positional.alerts import send_sell_alert
        send_sell_alert(ticker, fill, reason, entry_price=entry)
    except Exception:
        pass
    return True


def _maybe_convert_to_longterm(pos: dict, current_price: float) -> bool:
    """After a +2R partial, move the runner into the long-term book when the
    name's latest durability score clears the LT gate. Closes the swing
    position (reason CONVERT_TO_LT) and absorbs the quantity into
    lt_positions at market with no extra costs. Returns True on conversion."""
    from config import LT_BOOK_ENABLED, LT_CONVERT_FROM_SWING, LT_DURABILITY_GATE
    if not (LT_BOOK_ENABLED and LT_CONVERT_FROM_SWING):
        return False
    ticker = pos["ticker"]
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                """SELECT durability_score FROM pos_scans
                   WHERE ticker=? ORDER BY id DESC LIMIT 1""",
                (ticker,),
            ).fetchone()
        durability = float(row["durability_score"]) if row and row["durability_score"] is not None else None
        if durability is None or durability < LT_DURABILITY_GATE:
            return False
        qty = int(pos.get("quantity") or 0)
        if qty <= 0:
            return False
        if not _close_position(pos, current_price,
                               f"CONVERT_TO_LT: durability {durability:.0f} ≥ {LT_DURABILITY_GATE:.0f}"):
            return False
        from longterm.book import absorb_from_swing
        absorb_from_swing(ticker, qty, current_price, source_pos_id=pos["id"])
        return True
    except Exception as e:
        log.debug("[pos_runner] LT conversion failed for %s: %s", ticker, e)
        return False


# ── EOD Exit Management ───────────────────────────────────────────────────────

def _calendar_days_held(entry_date) -> int:
    """Calendar days a position has been held, derived from its entry date.

    Hold duration must come from the entry date — the old approach incremented
    a stored counter on every exit-check run, so extra EOD scans, manual
    triggers and server restarts inflated it (e.g. 51 "days" for a 16-day hold).
    """
    if not entry_date:
        return 0
    raw = str(entry_date)
    try:
        ed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            ed = datetime.fromisoformat(raw.replace("Z", "").split(".")[0].replace(" ", "T"))
        except ValueError:
            return 0
    return max(0, (datetime.now(IST).date() - ed.date()).days)


def run_exit_checks(force: bool = False) -> dict:
    """
    Check all OPEN pos_positions for exit conditions.
    Returns summary: {exited, sell_alerts, reentry_alerts, updated, errors}
    """
    if not force and not _is_trading_day():
        return {"skipped": True, "reason": "non-trading day"}

    log.info("[pos_runner] === EXIT CHECK START ===")
    from positional.risk import evaluate_exits, check_reentry, compute_ema21
    from positional.alerts import send_sell_alert, send_reentry_alert
    from db.models import get_conn

    exited = 0
    partials = 0
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

            # Derive hold duration from the entry date (not a per-run counter).
            # Set it on the pos dict too so check_time_stop sees the right value.
            days_held = _calendar_days_held(pos.get("entry_date"))
            pos["days_held"] = days_held

            # Partial de-risk at +R-multiple (before exit checks: the partial
            # mutates quantity and moves the stop to breakeven).
            if not int(pos.get("partial_taken") or 0):
                from positional.risk import compute_partial_trigger
                entry_px = float(pos.get("entry_price") or 0)
                stop_px  = float(pos.get("hard_stop") or 0)
                trigger  = compute_partial_trigger(entry_px, stop_px)
                if trigger and current_price >= trigger:
                    if _partial_close_position(pos, current_price):
                        partials += 1
                        # Swing → long-term conversion: a +2R runner on a
                        # durable business moves to the LT book instead of
                        # riding the swing trail (Phase 6; off unless
                        # LT_BOOK_ENABLED).
                        if _maybe_convert_to_longterm(pos, current_price):
                            exited += 1
                            continue

            # Evaluate exit (technical first, then optional management-based exit)
            exit_reason = evaluate_exits(pos, df)
            if not exit_reason:
                try:
                    from positional.research import management_exit_reason
                    exit_reason = management_exit_reason(ticker)
                except Exception:
                    exit_reason = None
            if exit_reason:
                _close_position(pos, current_price, exit_reason)
                sell_alerts_list.append({
                    "ticker": ticker,
                    "reason": exit_reason,
                    "current_price": current_price,
                })
                exited += 1
            else:
                # Persist the EMA-trail level + the trailing below-EMA count
                # already computed by check_ema_trailing_stop (no re-increment).
                ema21_val = compute_ema21(df)
                below_ema = int(pos.get("below_ema_consecutive", 0))
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
        "partials": partials,
        "sell_alerts": sell_alerts_list,
        "reentry_alerts": reentry_alerts_list,
        "updated": updated,
        "errors": errors,
    }
    log.info("[pos_runner] === EXIT CHECK END: exited=%d partials=%d updated=%d errors=%d ===",
             exited, partials, updated, errors)
    return summary


def _fetch_india_vix() -> float:
    """Fetch the latest close of ^INDIAVIX from yfinance. Returns a fallback value (15.0) on failure."""
    try:
        import yfinance as yf
        vix = yf.Ticker("^INDIAVIX")
        # Fetch 5 days of history to guarantee a valid close price
        df = vix.history(period="5d")
        if df is not None and not df.empty:
            close = df["Close"].dropna()
            if not close.empty:
                val = float(close.iloc[-1])
                log.info("[pos_runner] Fetched latest India VIX: %.2f", val)
                return val
        log.warning("[pos_runner] India VIX dataframe empty or null, using fallback 15.0")
    except Exception as e:
        log.warning("[pos_runner] Could not fetch India VIX: %s. Using fallback 15.0", e)
    return 15.0


def run_opportunity_swaps(open_positions: list[dict], buy_candidates: list[dict], regime_flag: str) -> list[dict]:
    """
    Evaluates currently held open positions for swapping opportunities.
    If a currently held stock is stagnant/underperforming (days_held >= min, pnl_pct < max)
    and a significantly better new buy candidate is available (score diff >= threshold),
    sells the held position and buys the new candidate.

    Returns list of executed swap dicts.
    """
    from config import (
        POSITIONAL_SWAP_ENABLED,
        POSITIONAL_SWAP_MIN_HOLD_DAYS,
        POSITIONAL_SWAP_SCORE_DIFF,
        POSITIONAL_SWAP_MAX_PNL_PCT,
    )

    swap_enabled = POSITIONAL_SWAP_ENABLED
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT positional_swap_enabled FROM bot_control WHERE id = 1"
            ).fetchone()
            if row and "positional_swap_enabled" in row.keys():
                swap_enabled = bool(row["positional_swap_enabled"])
    except Exception as e:
        log.warning("[pos_runner] Could not fetch positional_swap_enabled from bot_control: %s", e)

    if not swap_enabled:
        return []

    if not open_positions or not buy_candidates:
        return []

    log.info("[pos_runner] Checking for portfolio opportunity swaps (held: %d, candidates: %d)...",
             len(open_positions), len(buy_candidates))

    swaps_executed = []

    # 1. Filter eligible held positions (stagnant/underperforming)
    eligible_swaps = []
    for pos in open_positions:
        ticker = pos["ticker"]
        days_held = pos.get("days_held", 0)
        entry_price = float(pos["entry_price"])

        df = _fetch_daily_df(ticker)
        if df is None or df.empty:
            log.warning("[pos_runner] Swap check: could not fetch daily df for %s", ticker)
            continue
        last_close = float(df["Close"].iloc[-1])
        # Guard against NaN closes (yfinance can return an incomplete/empty
        # latest bar). Without this, NaN cascades through pnl_pct → fill price
        # → close_position and ultimately blows up the swap with
        # "cannot convert float NaN to integer".
        if last_close != last_close or entry_price <= 0:
            log.warning("[pos_runner] Swap check: invalid last close for %s "
                        "(close=%r entry=%r) — skipping",
                        ticker, last_close, entry_price)
            continue
        current_price = last_close
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        if days_held < POSITIONAL_SWAP_MIN_HOLD_DAYS:
            log.debug("[pos_runner] %s held %d days (< %d min), ineligible for swap",
                      ticker, days_held, POSITIONAL_SWAP_MIN_HOLD_DAYS)
            continue

        if pnl_pct >= POSITIONAL_SWAP_MAX_PNL_PCT:
            log.debug("[pos_runner] %s PnL is %.1f%% (>= %.1f%% max), winner letting it run",
                      ticker, pnl_pct, POSITIONAL_SWAP_MAX_PNL_PCT)
            continue

        # 2. Get technical score for this held position today
        from positional.scanner import scan_ticker
        scan_res = scan_ticker(ticker, df)
        if not scan_res:
            log.debug("[pos_runner] Swap check: scan failed for %s", ticker)
            continue
        current_score = scan_res["score"]

        eligible_swaps.append({
            "pos": pos,
            "ticker": ticker,
            "current_score": current_score,
            "current_price": current_price,
            "pnl_pct": pnl_pct
        })

    if not eligible_swaps:
        log.info("[pos_runner] No eligible stagnant positions for swapping today.")
        return []

    # Sort eligible swaps by their current score ascending (swap out worst scores first)
    eligible_swaps.sort(key=lambda x: x["current_score"])

    # Track which candidates are already held in open positions so we don't open duplicates
    held_tickers = {p["ticker"] for p in open_positions}

    # Available candidates copy
    available_candidates = list(buy_candidates)

    for swap_item in eligible_swaps:
        old_ticker = swap_item["ticker"]
        old_score = swap_item["current_score"]
        old_price = swap_item["current_price"]
        old_pnl = swap_item["pnl_pct"]
        pos = swap_item["pos"]

        best_cand = None
        for cand in available_candidates:
            new_ticker = cand["ticker"]
            new_score = cand["score"]

            if new_ticker in held_tickers:
                continue

            if new_score >= old_score + POSITIONAL_SWAP_SCORE_DIFF:
                best_cand = cand
                break

        if best_cand:
            new_ticker = best_cand["ticker"]
            new_score = best_cand["score"]
            new_price = best_cand["price"]
            reduce_size = best_cand.get("llm_verdict") == "REDUCE"

            log.info("[pos_runner] SWAP TRIGGERED: Replacing %s (Score %.1f, PnL %.1f%%) with %s (Score %.1f)",
                     old_ticker, old_score, old_pnl, new_ticker, new_score)

            # Executing swap:
            # A. Sell stagnant position first to release capital
            exit_reason = f"SWAP: Replaced by {new_ticker} (Score {new_score:.0f} vs {old_score:.0f})"
            close_ok = _close_position(pos, old_price, exit_reason)

            if close_ok:
                # B. Buy the superior candidate immediately
                entry_reason = f"SWAP: Replacing {old_ticker} (Score {new_score:.0f} vs {old_score:.0f})"
                opened = _open_position(
                    ticker=new_ticker,
                    price=new_price,
                    score=new_score,
                    scan_id=0,
                    regime_flag=regime_flag,
                    reason=entry_reason,
                    reduce_size=reduce_size
                )

                if opened:
                    # Successfully swapped!
                    # Add to held_tickers and remove from candidates to avoid repeated buys
                    held_tickers.add(new_ticker)
                    if best_cand in available_candidates:
                        available_candidates.remove(best_cand)

                    swaps_executed.append({
                        "old_ticker": old_ticker,
                        "new_ticker": new_ticker,
                        "old_score": old_score,
                        "new_score": new_score,
                        "old_price": old_price,
                        "new_price": new_price,
                        "pnl_pct": old_pnl
                    })

                    # Send dedicated swap Telegram alert
                    try:
                        from positional.alerts import send_swap_alert
                        send_swap_alert(
                            old_ticker=old_ticker,
                            new_ticker=new_ticker,
                            old_score=old_score,
                            new_score=new_score,
                            old_price=old_price,
                            new_price=new_price,
                            pnl_pct=old_pnl
                        )
                    except Exception as e:
                        log.warning("[pos_runner] Swap Telegram alert failed: %s", e)
                else:
                    log.error("[pos_runner] Swap execution: failed to open new position for %s after closing %s!",
                              new_ticker, old_ticker)

    log.info("[pos_runner] Opportunity swap check complete. Executed swaps: %d", len(swaps_executed))
    return swaps_executed


# ── EOD Scan ─────────────────────────────────────────────────────────────────

def run_eod_scan(force: bool = False) -> dict:
    """
    Main EOD scan: runs Minervini Trend Template + VCP on the fundamental universe.
    Opens positions for BUY alerts (paper mode) or sends SELL/BUY alerts.
    Supports dynamic VIX adjustments, LLM research, and opportunity swapping.
    Returns summary dict.
    """
    if not _positional_enabled():
        log.debug("[pos_runner] positional module disabled")
        return {"skipped": True, "reason": "positional_enabled=0"}
    if not force and not _is_trading_day():
        return {"skipped": True, "reason": "non-trading day"}

    log.info("[pos_runner] === EOD SCAN START ===")

    # Step 0: refresh the deterministic NSE event calendar + ASM/GSM
    # surveillance lists (both throttled inside; fail-open — a fetch failure
    # never stops the scan).
    try:
        from data.nse_calendar import refresh_event_calendar
        refresh_event_calendar()
    except Exception as e:
        log.debug("[pos_runner] event calendar refresh failed: %s", e)
    try:
        from data.hygiene import refresh_surveillance_lists
        refresh_surveillance_lists()
    except Exception as e:
        log.debug("[pos_runner] surveillance refresh failed: %s", e)
    try:
        from positional.ipo import sync_lockin_events
        sync_lockin_events()   # deterministic IPO supply events → event guard
    except Exception as e:
        log.debug("[pos_runner] lockin sync failed: %s", e)

    # Step 1: India VIX Check & Dynamic Score Threshold Adjustment
    import config
    import positional.scanner

    vix_value = _fetch_india_vix()
    if vix_value > config.POSITIONAL_VIX_HIGH_THRESHOLD:
        log.info("[pos_runner] High VIX regime (%.2f > %.2f). Tightening screening score threshold to 67.",
                 vix_value, config.POSITIONAL_VIX_HIGH_THRESHOLD)
        config.POSITIONAL_MIN_TREND_SCORE = 67
        positional.scanner.POSITIONAL_MIN_TREND_SCORE = 67
    else:
        log.info("[pos_runner] Standard VIX regime (%.2f). Score threshold is 60.", vix_value)
        config.POSITIONAL_MIN_TREND_SCORE = 60
        positional.scanner.POSITIONAL_MIN_TREND_SCORE = 60

    # Step 2: Market regime
    from positional.market_regime import get_latest_regime
    regime = get_latest_regime()
    regime_flag  = regime.get("flag", "NEUTRAL")
    size_mult    = float(regime.get("size_multiplier", 0.70))

    if regime_flag == "DEFENSIVE":
        log.info("[pos_runner] Regime=DEFENSIVE — reduced position sizes (%.0f%%)",
                 size_mult * 100)

    # Step 3: Exit management first
    exit_result = run_exit_checks(force=force)
    sell_alerts = exit_result.get("sell_alerts", [])
    reentry_alerts = exit_result.get("reentry_alerts", [])

    # Step 4: Technical scan
    from positional.scanner import run_eod_scan as _scan
    scan_results = _scan()
    buy_alerts_scanned = [r for r in scan_results if r["alert_type"] == "BUY"]
    longterm_watch = [r for r in scan_results if r.get("horizon") == "LONG_TERM"]

    # Step 5: Management-outlook research (analyst pass over BUY setups +
    # LONG_TERM watch candidates). Returns only the cleared buy pool; LONG_TERM
    # names are researched + persisted for the dashboard but never auto-bought.
    from config import POSITIONAL_LLM_RESEARCH_ENABLED
    buy_candidates = list(buy_alerts_scanned)
    if POSITIONAL_LLM_RESEARCH_ENABLED:
        from positional.research import run_positional_llm_research
        # A manually forced scan also forces fresh research (bypass analyst cache)
        # so prompt/logic changes are reflected across the whole candidate list.
        buy_candidates = run_positional_llm_research(
            buy_alerts_scanned + longterm_watch, vix_value, force=force
        )

    buy_alerts_taken: list[dict] = []
    processed_buy_tickers = set()

    # Step 6: Normal buying (fill empty slots)
    for result in buy_candidates:
        ticker = result["ticker"]
        if ticker in processed_buy_tickers:
            continue
        processed_buy_tickers.add(ticker)
        
        price  = result["price"]
        score  = result["score"]
        verdict = result.get("llm_verdict", "PROCEED")
        reduce_size = (verdict == "REDUCE")
        reason = result.get("llm_reason", f"EOD scan entry score={score:.0f}")

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
                reason=reason,
                reduce_size=reduce_size,
                est_hold_days=result.get("est_hold_days"),
            )
            if opened:
                buy_alerts_taken.append(result)
        except Exception as e:
            log.warning("[pos_runner] open_position failed for %s: %s", ticker, e)

    # Step 7: Opportunity Swaps
    swaps_executed = []
    try:
        from db.models import get_conn
        with get_conn() as conn:
            open_positions = conn.execute(
                "SELECT * FROM pos_positions WHERE status='OPEN'"
            ).fetchall()
        open_positions = [dict(p) for p in open_positions]

        # Remaining buy candidates that were NOT already taken in the normal entries
        taken_tickers = {b["ticker"] for b in buy_alerts_taken}
        remaining_candidates = [c for c in buy_candidates if c["ticker"] not in taken_tickers]

        swaps_executed = run_opportunity_swaps(open_positions, remaining_candidates, regime_flag)
    except Exception as e:
        log.error("[pos_runner] Opportunity swapping error: %s", e)

    # Step 8: Send EOD Telegram summary
    try:
        from positional.alerts import send_eod_summary
        time_stops = [s for s in sell_alerts if "TIME_STOP" in s.get("reason", "")]
        ema_exits  = [s for s in sell_alerts if "EMA_TRAIL" in s.get("reason", "")]
        hard_stops = [s for s in sell_alerts if "HARD_STOP" in s.get("reason", "")]
        send_eod_summary(
            regime=regime,
            buy_alerts=buy_candidates,  # use LLM-approved candidates
            sell_alerts=ema_exits + hard_stops,
            time_stops=time_stops,
            reentry_alerts=reentry_alerts,
            swaps=swaps_executed,
        )
    except Exception as e:
        log.warning("[pos_runner] Telegram summary failed: %s", e)

    # Step 9: feedback jobs (fail-open) — attach forward returns to past
    # signals and reconcile the guidance ledger against new actuals.
    try:
        from analytics.outcomes import compute_outcomes
        compute_outcomes()
    except Exception as e:
        log.debug("[pos_runner] outcomes job failed: %s", e)
    try:
        from positional.guidance import run_guidance_jobs
        run_guidance_jobs()
    except Exception as e:
        log.debug("[pos_runner] guidance jobs failed: %s", e)
    try:
        from longterm.book import run_longterm_book
        run_longterm_book()   # no-op unless LT_BOOK_ENABLED
    except Exception as e:
        log.debug("[pos_runner] LT book pass failed: %s", e)
    # Fundamentals coverage for every scan candidate (fetch_and_store caches
    # 24h, so reruns are nearly free). Keeps the Fundamentals page populated
    # for the same names that show up in Swing/Long-Term candidates.
    try:
        from data.fundamentals import fetch_and_store
        for r in scan_results[:60]:
            try:
                fetch_and_store(r["ticker"])
            except Exception:
                continue
    except Exception as e:
        log.debug("[pos_runner] candidate fundamentals fetch failed: %s", e)

    summary = {
        "regime": regime_flag,
        "vix": vix_value,
        "buy_alerts": len(buy_candidates),
        "positions_opened": len(buy_alerts_taken),
        "swaps_executed": len(swaps_executed),
        "positions_exited": exit_result.get("exited", 0),
        "partials": exit_result.get("partials", 0),
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

    # NOTE: no scan/research is triggered on startup. The full-universe
    # technical scan + LLM management research run ONLY at the scheduled
    # times below (POSITIONAL_SCAN_TIME / POSITIONAL_RESEARCH_REFRESH_TIME)
    # or via the manual UI triggers (/api/positional/scan and
    # /api/positional/research/refresh). This avoids re-scanning the whole
    # universe and re-running LLM summaries on every server restart.

    _last_scan_date:   object = None
    _last_alert_date:  object = None
    _last_regime_month: object = None
    _last_refresh_date: object = None
    _last_universe_date: object = None

    scan_h,  scan_m  = [int(x) for x in POSITIONAL_SCAN_TIME.split(":")]
    alert_h, alert_m = [int(x) for x in POSITIONAL_ALERT_TIME.split(":")]
    refresh_h, refresh_m = [int(x) for x in POSITIONAL_RESEARCH_REFRESH_TIME.split(":")]

    # If booted after a scheduled time, mark it as already handled so we do
    # NOT auto-run a catch-up scan / research pass on startup. The scheduled
    # work has effectively been missed for this boot — trigger it manually from
    # the UI if needed; otherwise it resumes at its scheduled time tomorrow.
    now = datetime.now(IST)
    if (now.hour, now.minute) >= (scan_h, scan_m):
        _last_scan_date = now.date()
    if (now.hour, now.minute) >= (alert_h, alert_m):
        _last_alert_date = now.date()
    if (now.hour, now.minute) >= (refresh_h, refresh_m):
        _last_refresh_date = now.date()
    # Regime is a monthly job (first trading days of the month). Mark the
    # current month handled on boot so a fresh start within that window does
    # not auto-recompute it — use the manual trigger or wait for next month.
    _last_regime_month = now.month

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

            # Weekly unified-universe refresh (Phase 4): re-run the Screener
            # pipeline + quality scoring + positional sync on the scheduled
            # weekday (default Saturday — markets closed, scrape freely).
            from config import (UNIVERSE_WEEKLY_REFRESH_ENABLED,
                                UNIVERSE_REFRESH_WEEKDAY, UNIVERSE_REFRESH_TIME)
            uh, um = [int(x) for x in UNIVERSE_REFRESH_TIME.split(":")]
            if (UNIVERSE_WEEKLY_REFRESH_ENABLED
                    and today.weekday() == UNIVERSE_REFRESH_WEEKDAY
                    and (now.hour, now.minute) >= (uh, um)
                    and _last_universe_date != today):
                _last_universe_date = today
                try:
                    from longterm.tasks import run_phase_a
                    log.info("[pos_runner] weekly universe refresh starting")
                    run_phase_a(sync_positional=True)
                except Exception as e:
                    log.error("[pos_runner] weekly universe refresh error: %s", e)
                time.sleep(30)
                continue

            # Daily management-research refresh (holdings + watchlist + shortlist).
            # Decoupled from the technical scan so holdings pick up new concalls.
            past_refresh = (now.hour, now.minute) >= (refresh_h, refresh_m)
            if past_refresh and _is_trading_day() and _last_refresh_date != today:
                _last_refresh_date = today
                try:
                    from positional.research import refresh_management_research
                    refresh_management_research()
                except Exception as e:
                    log.error("[pos_runner] research refresh error: %s", e)
                time.sleep(30)
                continue

            # 4:00 PM: EOD scan
            if past_scan and _is_trading_day() and _last_scan_date != today:
                _last_scan_date = today
                try:
                    run_eod_scan(force=False)
                except Exception as e:
                    log.error("[pos_runner] EOD scan error: %s", e)
                time.sleep(30)
                continue

            time.sleep(30)
        except Exception as e:
            log.error("[pos_runner] daemon loop error: %s", e)
            time.sleep(60)

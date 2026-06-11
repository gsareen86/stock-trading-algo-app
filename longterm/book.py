"""
Long-term book (Phase 6) — durability-first, thesis-stopped, paper/advisory.

Until now LONG_TERM-classified scan rows were informational: nothing acted
on them. This module runs a separate paper book (LT_CAPITAL pool) with the
design's rules:

  Entry (staggered tranches, LT_TRANCHE_FRACTIONS):
    T1  on classification: latest scan horizon='LONG_TERM' (or 'BOTH'),
        durability ≥ LT_DURABILITY_GATE, research verdict not SKIP/AVOID,
        hygiene + sector cap + capacity clear.
    T2  ≥ LT_MIN_TRANCHE_GAP_DAYS later, on either a controlled drawdown
        (price 8–15% below T1 with the verdict intact) or a trend
        reconfirmation (close back above a rising 21 EMA).
    T3  after the guidance ledger reconciles a MET/BEAT row newer than T2
        (management delivered → finish the position).

  Conversion: a swing position that takes its +2R partial with durability
    ≥ gate moves its runner into this book at market (no extra costs — a
    reclassification, not a trade).

  Exit — thesis stops only (no time stop):
    * guidance miss streak ≥ LT_GUIDANCE_MISS_STREAK_EXIT
    * research verdict turns SKIP / management score ≤ veto threshold
    * governance tripwire: promoter pledge jumps >10pp QoQ
    * crash protection: close < 40-week MA while macro regime is DEFENSIVE
      → halve once (not exit)

The whole book is gated behind LT_BOOK_ENABLED (default False) so it never
surprises anyone; when disabled, nothing here runs.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from config import IST

log = logging.getLogger(__name__)


def _bare(ticker: str) -> str:
    return ticker.split(".")[0].strip().upper()


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _daily_df(ticker: str):
    try:
        from data.fetcher import fetch_candles
        df = fetch_candles(ticker, interval="1d", days=420)
        return df if df is not None and not df.empty else None
    except Exception:
        return None


def _last_close(df) -> Optional[float]:
    try:
        px = float(df["Close"].iloc[-1])
        return px if px == px and px > 0 else None
    except Exception:
        return None


# ── Book accounting ──────────────────────────────────────────────────────────

def _open_lt_positions() -> list[dict]:
    from db.models import get_conn
    try:
        with get_conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM lt_positions WHERE status='OPEN'"
            ).fetchall()]
    except Exception:
        return []


def _lt_cash() -> float:
    from config import LT_CAPITAL
    invested = sum((p.get("avg_entry_price") or 0) * (p.get("quantity") or 0)
                   for p in _open_lt_positions())
    return max(LT_CAPITAL - invested, 0.0)


def _sector_of(ticker: str) -> str:
    from db.models import get_conn
    base = _bare(ticker)
    try:
        with get_conn() as conn:
            for sql in (
                "SELECT sector FROM fundamentals WHERE ticker=?",
                "SELECT sector FROM pos_universe WHERE ticker=? OR ticker=?",
                "SELECT sector FROM lt_universe WHERE ticker=?",
            ):
                params = (base, base + ".NS") if sql.count("?") == 2 else (base,)
                row = conn.execute(sql, params).fetchone()
                if row and row["sector"]:
                    return str(row["sector"])
    except Exception:
        pass
    return ""


def _sector_exposure(sector: str) -> float:
    if not sector:
        return 0.0
    return sum((p.get("avg_entry_price") or 0) * (p.get("quantity") or 0)
               for p in _open_lt_positions()
               if (p.get("sector") or "") == sector)


def _record_trade(conn, position_id: int, ticker: str, side: str, qty: int,
                  price: float, costs: float, pnl: float, reason: str) -> None:
    conn.execute(
        """INSERT INTO lt_trades (ts, ticker, side, quantity, price, costs,
                                  pnl, reason, position_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (_now_iso(), ticker, side, qty, price, round(costs, 2),
         round(pnl, 2), reason, position_id),
    )


def _buy_tranche(ticker: str, price: float, tranche_idx: int,
                 reason: str, source: str = "classified",
                 qty_override: Optional[int] = None,
                 zero_cost: bool = False) -> bool:
    """Open the position (tranche 1) or add the next tranche."""
    from config import LT_CAPITAL, LT_MAX_POSITION_PCT, LT_TRANCHE_FRACTIONS
    from positional.risk import compute_delivery_costs
    from db.models import get_conn, insert_returning_id

    target_alloc = LT_CAPITAL * LT_MAX_POSITION_PCT
    fraction = LT_TRANCHE_FRACTIONS[min(tranche_idx, len(LT_TRANCHE_FRACTIONS) - 1)]
    qty = qty_override if qty_override is not None else int(target_alloc * fraction / price)
    if qty <= 0:
        return False
    cost_amount = qty * price
    if qty_override is None and cost_amount > _lt_cash():
        log.info("[lt_book] %s: tranche skipped — insufficient LT cash", ticker)
        return False
    costs = 0.0 if zero_cost else compute_delivery_costs("BUY", price, qty)
    sector = _sector_of(ticker)

    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM lt_positions WHERE ticker=? AND status='OPEN'",
                (_bare(ticker),),
            ).fetchone()
            if row:
                pos = dict(row)
                old_qty = int(pos["quantity"] or 0)
                old_avg = float(pos["avg_entry_price"] or price)
                new_qty = old_qty + qty
                new_avg = (old_qty * old_avg + qty * price) / new_qty
                conn.execute(
                    """UPDATE lt_positions
                       SET quantity=?, avg_entry_price=?, tranches_taken=?,
                           last_tranche_at=?
                       WHERE id=?""",
                    (new_qty, round(new_avg, 2),
                     int(pos["tranches_taken"] or 0) + 1, _now_iso(), pos["id"]),
                )
                pos_id = pos["id"]
            else:
                pos_id = insert_returning_id(
                    conn,
                    """INSERT INTO lt_positions
                       (ticker, opened_at, status, quantity, avg_entry_price,
                        tranches_taken, last_tranche_at, halved, source, sector)
                       VALUES (?,?,?,?,?,?,?,0,?,?)""",
                    (_bare(ticker), _now_iso(), "OPEN", qty, round(price, 2),
                     1, _now_iso(), source, sector),
                )
            _record_trade(conn, pos_id, _bare(ticker), "BUY", qty, price,
                          costs, 0.0, reason)
    except Exception as e:
        log.error("[lt_book] tranche write failed for %s: %s", ticker, e)
        return False

    log.info("[lt_book] TRANCHE %d: %s qty=%d @ %.2f (%s)",
             tranche_idx + 1, ticker, qty, price, reason)
    return True


def _sell_lt(pos: dict, price: float, qty: int, reason: str,
             close: bool) -> bool:
    from positional.risk import compute_delivery_costs
    from db.models import get_conn

    qty = min(qty, int(pos["quantity"] or 0))
    if qty <= 0:
        return False
    avg = float(pos["avg_entry_price"] or price)
    costs = compute_delivery_costs("SELL", price, qty)
    pnl = (price - avg) * qty - costs
    pnl_pct = (price - avg) / avg * 100 if avg else 0.0

    try:
        with get_conn() as conn:
            if close or qty >= int(pos["quantity"] or 0):
                conn.execute(
                    """UPDATE lt_positions
                       SET status='CLOSED', quantity=0, exit_date=?, exit_price=?,
                           exit_reason=?, pnl=?, pnl_pct=?
                       WHERE id=?""",
                    (_now_iso(), price, reason, round(pnl, 2),
                     round(pnl_pct, 2), pos["id"]),
                )
            else:
                conn.execute(
                    "UPDATE lt_positions SET quantity=?, halved=1 WHERE id=?",
                    (int(pos["quantity"]) - qty, pos["id"]),
                )
            _record_trade(conn, pos["id"], pos["ticker"], "SELL", qty, price,
                          costs, pnl, reason)
    except Exception as e:
        log.error("[lt_book] sell write failed for %s: %s", pos["ticker"], e)
        return False

    log.info("[lt_book] %s: %s qty=%d @ %.2f pnl=%.2f — %s",
             "CLOSED" if close else "HALVED", pos["ticker"], qty, price, pnl, reason)
    try:
        from positional.alerts import send_sell_alert
        send_sell_alert(pos["ticker"], price, f"[LT book] {reason}", entry_price=avg)
    except Exception:
        pass
    return True


# ── Thesis stops ─────────────────────────────────────────────────────────────

def _pledge_jump_pp(ticker: str) -> Optional[float]:
    """Promoter pledge change (pp) between the two latest quarters, from the
    lt_universe raw_inputs shareholding snapshot. None when unavailable."""
    from db.models import get_conn
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT raw_inputs FROM lt_universe WHERE ticker=?", (_bare(ticker),)
            ).fetchone()
        if not row or not row["raw_inputs"]:
            return None
        raw = json.loads(row["raw_inputs"])
        recent = raw.get("shareholding_recent") or []
        pledges = [q.get("pledged_pct") for q in recent if q.get("pledged_pct") is not None]
        if len(pledges) >= 2:
            return float(pledges[0]) - float(pledges[1])  # most-recent-first
    except Exception:
        pass
    return None


def _research_state(ticker: str) -> dict:
    from db.models import get_conn
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT verdict, management_score FROM pos_research
                   WHERE ticker=?""", (_bare(ticker),),
            ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def _thesis_exit_reason(pos: dict) -> Optional[str]:
    from config import LT_GUIDANCE_MISS_STREAK_EXIT, POSITIONAL_MANAGEMENT_VETO_SCORE
    ticker = pos["ticker"]

    try:
        from positional.guidance import miss_streak
        streak = miss_streak(ticker)
        if streak >= LT_GUIDANCE_MISS_STREAK_EXIT:
            return f"THESIS_STOP: guidance missed {streak} consecutive quarters"
    except Exception:
        pass

    rs = _research_state(ticker)
    verdict = str(rs.get("verdict") or "").upper()
    mgmt = rs.get("management_score")
    if verdict == "SKIP":
        return "THESIS_STOP: research verdict turned SKIP"
    if mgmt is not None and float(mgmt) <= POSITIONAL_MANAGEMENT_VETO_SCORE:
        return f"THESIS_STOP: management score {float(mgmt):.0f} ≤ veto threshold"

    jump = _pledge_jump_pp(ticker)
    if jump is not None and jump > 10.0:
        return f"GOVERNANCE_TRIPWIRE: promoter pledge +{jump:.1f}pp QoQ"

    return None


def _crash_protection_due(pos: dict, df) -> bool:
    """Close < 40-week MA while the macro regime is DEFENSIVE → halve once."""
    from config import LT_CRASH_MA_WEEKS
    if int(pos.get("halved") or 0):
        return False
    try:
        from positional.market_regime import get_latest_regime
        if str(get_latest_regime().get("flag", "")).upper() != "DEFENSIVE":
            return False
        close = df["Close"].astype(float)
        n = LT_CRASH_MA_WEEKS * 5
        if len(close) < n:
            return False
        ma = float(close.tail(n).mean())
        return float(close.iloc[-1]) < ma
    except Exception:
        return False


# ── Entries ──────────────────────────────────────────────────────────────────

def _lt_candidates() -> list[dict]:
    """Latest scan row per ticker with horizon LONG_TERM/BOTH and durability
    ≥ the gate; research verdict must not be SKIP/AVOID."""
    from config import LT_DURABILITY_GATE
    from db.models import get_conn
    try:
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute(
                """SELECT s.ticker, s.price, s.durability_score, s.horizon
                   FROM pos_scans s
                   JOIN (SELECT ticker, MAX(id) AS max_id FROM pos_scans GROUP BY ticker) m
                     ON m.max_id = s.id
                   WHERE s.horizon IN ('LONG_TERM','BOTH')
                     AND s.durability_score >= ?""",
                (LT_DURABILITY_GATE,),
            ).fetchall()]
    except Exception:
        return []
    out = []
    for r in rows:
        verdict = str(_research_state(r["ticker"]).get("verdict") or "").upper()
        if verdict in ("SKIP", "AVOID"):
            continue
        # Compounding requires evidence of delivery: recent IPOs must show
        # LT_MIN_LISTING_AGE_DAYS of post-listing life before this book buys.
        # The swing book may trade their momentum; long-term waits for proof.
        try:
            from config import LT_MIN_LISTING_AGE_DAYS
            from positional.ipo import listing_date
            ld = listing_date(r["ticker"])
            if ld:
                from datetime import date as _d
                age = (_d.today() - _d.fromisoformat(ld)).days
                if age < LT_MIN_LISTING_AGE_DAYS:
                    continue
        except Exception:
            pass
        out.append(r)
    return out


def _guidance_confirmed_since(ticker: str, since_iso: Optional[str]) -> bool:
    """True if a MET/BEAT guidance row was reconciled after `since_iso`."""
    from db.models import get_conn
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT MAX(reconciled_at) AS m FROM guidance_ledger
                   WHERE ticker=? AND delivered IN ('MET','BEAT')""",
                (_bare(ticker),),
            ).fetchone()
        latest = row["m"] if row else None
        return bool(latest and (not since_iso or str(latest) > str(since_iso)))
    except Exception:
        return False


def _days_since(iso: Optional[str]) -> int:
    if not iso:
        return 10**6
    try:
        dt = datetime.fromisoformat(str(iso))
        ref = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return max(0, (ref.date() - dt.date()).days)
    except ValueError:
        return 10**6


def _maybe_add_tranche(pos: dict) -> bool:
    """Tranche-2/3 logic for an open LT position."""
    from config import LT_MIN_TRANCHE_GAP_DAYS, LT_TRANCHE_FRACTIONS
    tranches = int(pos.get("tranches_taken") or 0)
    if tranches >= len(LT_TRANCHE_FRACTIONS):
        return False
    if _days_since(pos.get("last_tranche_at")) < LT_MIN_TRANCHE_GAP_DAYS:
        return False

    ticker = pos["ticker"]
    df = _daily_df(ticker)
    price = _last_close(df) if df is not None else None
    if price is None:
        return False
    avg = float(pos.get("avg_entry_price") or price)

    if tranches == 1:
        # T2a: controlled drawdown with thesis intact
        drawdown_pct = (price - avg) / avg * 100
        if -15.0 <= drawdown_pct <= -8.0:
            return _buy_tranche(ticker, price, 1,
                                f"T2 drawdown add ({drawdown_pct:.1f}% below T1)")
        # T2b: trend reconfirmation — close above a rising 21 EMA
        try:
            close = df["Close"].astype(float)
            ema21 = close.ewm(span=21, adjust=False).mean()
            if (float(close.iloc[-1]) > float(ema21.iloc[-1])
                    and float(ema21.iloc[-1]) > float(ema21.iloc[-6])):
                return _buy_tranche(ticker, price, 1, "T2 trend reconfirmation (21EMA rising)")
        except Exception:
            pass
        return False

    # T3: management delivered since the last tranche
    if _guidance_confirmed_since(ticker, pos.get("last_tranche_at")):
        return _buy_tranche(ticker, price, 2, "T3 guidance delivered (MET/BEAT)")
    return False


def _in_reentry_quarantine(ticker: str) -> bool:
    """A name that hit a thesis stop / governance tripwire may not re-enter
    the book for LT_REENTRY_QUARANTINE_DAYS — the thesis broke; a fresh scan
    score the next day doesn't repair it."""
    from config import LT_REENTRY_QUARANTINE_DAYS
    from db.models import get_conn
    try:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT exit_date, exit_reason FROM lt_positions
                   WHERE ticker=? AND status='CLOSED'
                   ORDER BY id DESC LIMIT 1""",
                (_bare(ticker),),
            ).fetchone()
        if not row or not row["exit_date"]:
            return False
        reason = str(row["exit_reason"] or "")
        if not (reason.startswith("THESIS_STOP") or reason.startswith("GOVERNANCE")):
            return False
        return _days_since(row["exit_date"]) < LT_REENTRY_QUARANTINE_DAYS
    except Exception:
        return False


# ── Swing → LT conversion ────────────────────────────────────────────────────

def absorb_from_swing(ticker: str, qty: int, price: float,
                      source_pos_id: int) -> bool:
    """Move a swing runner into the LT book at market. A reclassification,
    not a trade — no transaction costs are charged on the LT side."""
    return _buy_tranche(ticker, price, 0,
                        f"CONVERT_FROM_SWING (pos_positions id={source_pos_id})",
                        source="conversion", qty_override=qty, zero_cost=True)


# ── Daily driver ─────────────────────────────────────────────────────────────

def run_longterm_book() -> dict:
    """Daily pass: thesis stops → crash protection → tranche adds → new T1s.
    No-op unless LT_BOOK_ENABLED."""
    from config import (LT_BOOK_ENABLED, LT_MAX_POSITIONS, LT_CAPITAL,
                        LT_SECTOR_CAP_PCT, LT_TRANCHE_FRACTIONS,
                        LT_MAX_POSITION_PCT)
    if not LT_BOOK_ENABLED:
        return {"skipped": True, "reason": "LT_BOOK_ENABLED=False"}

    exited = halved = added = opened = 0

    # 1. Exits / crash protection on open positions
    for pos in _open_lt_positions():
        df = _daily_df(pos["ticker"])
        price = _last_close(df) if df is not None else None
        if price is None:
            continue
        reason = _thesis_exit_reason(pos)
        if reason:
            if _sell_lt(pos, price, int(pos["quantity"]), reason, close=True):
                exited += 1
            continue
        if _crash_protection_due(pos, df):
            if _sell_lt(pos, price, int(pos["quantity"]) // 2,
                        "CRASH_PROTECTION: close < 40-week MA in DEFENSIVE regime",
                        close=False):
                halved += 1

    # 2. Tranche additions
    for pos in _open_lt_positions():
        if _maybe_add_tranche(pos):
            added += 1

    # 3. New tranche-1 entries
    open_now = _open_lt_positions()
    held = {p["ticker"] for p in open_now}
    for cand in _lt_candidates():
        if len(held) + opened >= LT_MAX_POSITIONS:
            break
        ticker = _bare(cand["ticker"])
        if ticker in held:
            continue
        if _in_reentry_quarantine(ticker):
            continue
        try:
            from data.hygiene import hygiene_check
            if not hygiene_check(ticker)["passed"]:
                continue
        except Exception:
            pass
        sector = _sector_of(ticker)
        t1_value = LT_CAPITAL * LT_MAX_POSITION_PCT * LT_TRANCHE_FRACTIONS[0]
        if sector and _sector_exposure(sector) + t1_value > LT_CAPITAL * LT_SECTOR_CAP_PCT:
            log.info("[lt_book] %s: skipped — sector cap (%s)", ticker, sector)
            continue
        price = cand.get("price")
        if not price or price <= 0:
            df = _daily_df(ticker)
            price = _last_close(df) if df is not None else None
        if not price:
            continue
        if _buy_tranche(ticker, float(price), 0,
                        f"T1 classification (durability={cand.get('durability_score'):.0f}, "
                        f"horizon={cand.get('horizon')})"):
            opened += 1
            held.add(ticker)

    summary = {"opened": opened, "tranches_added": added,
               "exited": exited, "halved": halved,
               "open_positions": len(_open_lt_positions()),
               "cash": round(_lt_cash(), 2)}
    log.info("[lt_book] daily pass: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_longterm_book())

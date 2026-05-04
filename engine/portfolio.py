"""
Portfolio state: cash, open positions, realized + unrealized P&L, snapshots.
All state is persisted in the configured DB (SQLite or Supabase Postgres);
the dashboard reads straight from DB.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from config import INITIAL_CAPITAL
from data.fetcher import latest_price
from db.models import get_conn, insert_returning_id, query_df
from engine.paper_broker import execute

log = logging.getLogger(__name__)


# ---------- Initialization ----------


def initialize_if_empty() -> None:
    """Seed the first portfolio snapshot with full cash if no snapshots exist."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM portfolio_snapshots").fetchone()
        if row["n"] == 0:
            conn.execute(
                """INSERT INTO portfolio_snapshots
                   (ts, cash, equity, total_value, unrealized_pnl, realized_pnl, open_positions)
                   VALUES (?, ?, 0, ?, 0, 0, 0)""",
                (datetime.utcnow().isoformat(), INITIAL_CAPITAL, INITIAL_CAPITAL),
            )


def get_cash() -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT cash FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return float(row["cash"]) if row else INITIAL_CAPITAL


def realized_pnl_total() -> float:
    """Total realised P&L = closed-position P&L + partial-T1 P&L on still-open
    positions.

    Previously this only summed ``positions.pnl`` (written on FULL close),
    missing the partial-T1 SELL/COVER legs that book real P&L while the
    position remains open. That made the dashboard's "Realized P&L" diverge
    from cash by exactly the sum of those partial gains.
    """
    with get_conn() as conn:
        closed_row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) AS total FROM positions WHERE status='CLOSED'"
        ).fetchone()
        closed_pnl = float(closed_row["total"] or 0)

        # Partial-T1 realised on still-open positions: every SELL or COVER row
        # against an OPEN position is a closing leg. P&L per leg = net_value -
        # entry_price*qty. (LONG SELL: net_value=+sale_proceeds-costs, subtract
        # entry cost basis. SHORT COVER: partial_close stores net_value=
        # entry*qty+pnl, so the same formula yields pnl exactly.)
        partial_rows = conn.execute(
            """SELECT t.quantity AS q, t.net_value AS nv, p.entry_price AS e
               FROM trades t
               JOIN positions p ON p.id = t.position_id
               WHERE p.status = 'OPEN' AND t.side IN ('SELL', 'COVER')"""
        ).fetchall()
    partial_pnl = sum(
        float(r["nv"]) - float(r["e"]) * int(r["q"]) for r in partial_rows
    )
    return closed_pnl + partial_pnl


# ---------- Position queries ----------


def open_positions(conn=None) -> List[dict]:
    """Query OPEN positions. Pass an existing conn to see uncommitted state."""
    if conn is not None:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status='OPEN' ORDER BY entry_ts"
        ).fetchall()
        return [dict(r) for r in rows]
    with get_conn() as conn2:
        rows = conn2.execute(
            "SELECT * FROM positions WHERE status='OPEN' ORDER BY entry_ts"
        ).fetchall()
    return [dict(r) for r in rows]


def is_open(ticker: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM positions WHERE ticker=? AND status='OPEN' LIMIT 1",
            (ticker,),
        ).fetchone()
    return row is not None


# ---------- Order entry / exit ----------


def open_position(ticker: str, price: float, quantity: int, *,
                  stop_loss: Optional[float] = None,
                  take_profit: Optional[float] = None,
                  strategy: str = "", composite_score: float = 0,
                  reason: str = "", mode: str = "manual",
                  prices: Dict[str, float] | None = None,
                  atr_at_entry: Optional[float] = None,
                  t1_target: Optional[float] = None,
                  side: str = "LONG") -> Optional[int]:
    """Open a LONG (BUY) or SHORT (SELL) position.

    For paper trading we model SHORT cash flow the same way Indian discount
    brokers handle MIS: the broker blocks margin equal to the position
    notional and returns it on cover. So:

        LONG  open : cash -= entry_value + costs
        SHORT open : cash -= entry_value + costs   (margin block)

    The P&L direction is reversed at exit time inside ``close_position`` /
    ``partial_close_position``. ``high_water_mark`` is overloaded —
    for LONGs it's the highest price seen since entry; for SHORTs it
    is the LOWEST price seen since entry (renaming would break callers).
    """
    side = (side or "LONG").upper()
    if side not in {"LONG", "SHORT"}:
        log.warning("invalid side %r — defaulting to LONG", side)
        side = "LONG"

    cash = get_cash()
    # Both LONG and SHORT block margin equal to the entry notional. We
    # reuse the BUY broker call to compute fill price + costs identically.
    exec_ = execute("BUY", price, quantity)
    cost = -exec_.net  # exec_.net is negative on BUY-side execution
    if cost > cash:
        log.warning("insufficient cash for %s %s qty=%d cost=%.2f cash=%.2f",
                    side, ticker, quantity, cost, cash)
        return None

    trade_side = "BUY" if side == "LONG" else "SHORT"
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        position_id = insert_returning_id(
            conn,
            """INSERT INTO positions
               (ticker, entry_ts, entry_price, quantity, stop_loss, take_profit,
                strategy, composite_score, status,
                atr_at_entry, t1_target, t1_taken, high_water_mark,
                initial_quantity, side)
               VALUES (?,?,?,?,?,?,?,?, 'OPEN', ?, ?, 0, ?, ?, ?)""",
            (ticker, now, exec_.fill_price, quantity, stop_loss, take_profit,
             strategy, composite_score,
             atr_at_entry, t1_target, exec_.fill_price, quantity, side),
        )
        conn.execute(
            """INSERT INTO trades
               (ts, ticker, side, quantity, price, value, costs, net_value,
                strategy, reason, composite_score, mode, position_id)
               VALUES (?,?, ?, ?,?,?,?,?,?,?,?,?,?)""",
            (now, ticker, trade_side, quantity, exec_.fill_price, exec_.gross,
             exec_.total_costs, exec_.net, strategy, reason, composite_score,
             mode, position_id),
        )

    new_cash = cash + exec_.net  # net is negative on BUY-side execution
    _snapshot_row(new_cash, prices=prices or {ticker: exec_.fill_price})

    log.info("OPEN %s %s %d @ %.2f cost=%.2f atr=%s t1=%s",
             side, ticker, quantity, exec_.fill_price, -exec_.net,
             f"{atr_at_entry:.2f}" if atr_at_entry else "—",
             f"{t1_target:.2f}" if t1_target else "—")
    return position_id


def partial_close_position(position_id: int, price: float, qty: int, *,
                           reason: str = "T1 partial",
                           mode: str = "auto") -> Optional[float]:
    """Reduce an open LONG or SHORT by ``qty`` shares without closing it.

    LONG  partial : SELL qty. cash inflow = exec_.net.
    SHORT partial : COVER qty. cash inflow = (entry*qty + partial_pnl).
    """
    with get_conn() as conn:
        pos = conn.execute(
            "SELECT * FROM positions WHERE id=? AND status='OPEN'",
            (position_id,),
        ).fetchone()
        if not pos:
            return None
        remaining = int(pos["quantity"])
        if qty <= 0 or qty >= remaining:
            return None
        ticker = pos["ticker"]
        entry = float(pos["entry_price"])
        side = (pos["side"] if "side" in pos.keys() else "LONG") or "LONG"

    exec_ = execute("SELL", price, qty)
    if side == "LONG":
        entry_cost_partial = entry * qty
        pnl = exec_.net - entry_cost_partial
        cash_delta = exec_.net
        trade_side = "SELL"
    else:  # SHORT partial cover
        gross_pnl = (entry - price) * qty
        pnl = gross_pnl - exec_.total_costs
        cash_delta = (entry * qty) + pnl
        trade_side = "COVER"

    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """UPDATE positions
                SET quantity = quantity - ?,
                    t1_taken = 1
              WHERE id = ?""",
            (qty, position_id),
        )
        conn.execute(
            """INSERT INTO trades
               (ts, ticker, side, quantity, price, value, costs, net_value,
                strategy, reason, composite_score, mode, position_id)
               VALUES (?,?, ?, ?,?,?,?,?,?,?,?,?,?)""",
            (now, ticker, trade_side, qty, exec_.fill_price, exec_.gross,
             exec_.total_costs, cash_delta, pos["strategy"], reason,
             pos["composite_score"], mode, position_id),
        )

    new_cash = get_cash() + cash_delta
    _snapshot_row(new_cash)

    log.info("PARTIAL %s %s sold %d/%d @ %.2f PnL=%.2f [%s]",
             side, ticker, qty, remaining, exec_.fill_price, pnl, reason)
    return pnl


def update_position_levels(position_id: int, *,
                           stop_loss: Optional[float] = None,
                           high_water_mark: Optional[float] = None) -> None:
    """Mutate an open position's stop and/or HWM. Used by the trailing-stop
    update inside the cycle's exit pass."""
    sets = []
    params: list = []
    if stop_loss is not None:
        sets.append("stop_loss = ?")
        params.append(stop_loss)
    if high_water_mark is not None:
        sets.append("high_water_mark = ?")
        params.append(high_water_mark)
    if not sets:
        return
    params.append(position_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE positions SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )


def close_position(position_id: int, price: float, *, reason: str = "",
                   mode: str = "auto") -> Optional[float]:
    """Close an open LONG or SHORT. Returns realised P&L after costs.

    LONG  : SELL the held shares. P&L = exit_proceeds - entry_cost.
    SHORT : BUY back the borrowed shares. We model this as the broker
            returning the original margin block (entry_value) plus the
            P&L = (entry - exit) * qty - costs.
    """
    with get_conn() as conn:
        pos = conn.execute(
            "SELECT * FROM positions WHERE id=? AND status='OPEN'", (position_id,)
        ).fetchone()
        if not pos:
            return None
        qty = pos["quantity"]
        entry = float(pos["entry_price"])
        ticker = pos["ticker"]
        side = (pos["side"] if "side" in pos.keys() else "LONG") or "LONG"

    if side == "LONG":
        exec_ = execute("SELL", price, qty)
        proceeds = exec_.net          # +ve on SELL
        entry_cost = entry * qty
        pnl = proceeds - entry_cost
        cash_delta = exec_.net        # +ve cash inflow
        trade_side = "SELL"
    else:  # SHORT cover
        exec_ = execute("SELL", price, qty)  # uses same cost model
        cover_cost_gross = price * qty
        # cash returns: original margin block + P&L on the short
        # P&L = (entry - exit) * qty - all costs (entry costs were deducted
        # at open as part of the margin block)
        gross_pnl = (entry - price) * qty
        # exec_.total_costs is the cover-leg cost; subtract it from P&L
        pnl = gross_pnl - exec_.total_costs
        # Cash inflow = original notional + pnl  (margin returned + profit)
        cash_delta = (entry * qty) + pnl
        trade_side = "COVER"

    entry_cost_basis = entry * qty
    pnl_pct = (pnl / entry_cost_basis) * 100 if entry_cost_basis else 0

    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """UPDATE positions
                SET status='CLOSED', exit_ts=?, exit_price=?, pnl=?, pnl_pct=?
              WHERE id=?""",
            (now, exec_.fill_price, pnl, pnl_pct, position_id),
        )
        conn.execute(
            """INSERT INTO trades
               (ts, ticker, side, quantity, price, value, costs, net_value,
                strategy, reason, composite_score, mode, position_id)
               VALUES (?,?, ?, ?,?,?,?,?,?,?,?,?,?)""",
            (now, ticker, trade_side, qty, exec_.fill_price, exec_.gross,
             exec_.total_costs, cash_delta, pos["strategy"], reason,
             pos["composite_score"], mode, position_id),
        )

    new_cash = get_cash() + cash_delta
    _snapshot_row(new_cash)

    log.info("CLOSE %s %s qty=%d @ %.2f PnL=%.2f (%+.2f%%) [%s]",
             side, ticker, qty, exec_.fill_price, pnl, pnl_pct, reason)
    return pnl


# ---------- Snapshots ----------


def _current_equity(prices: Dict[str, float] | None = None) -> tuple[float, float, int]:
    """Return (equity_value, unrealized_pnl, open_count) for open positions.

    For SHORTs the "equity" parked is the original margin block (entry*qty);
    unrealised P&L is (entry - current) * qty. For LONGs it's the usual
    current * qty / (current - entry) * qty.
    """
    equity = 0.0
    unreal = 0.0
    positions = open_positions()
    for p in positions:
        price = (prices or {}).get(p["ticker"])
        if not price:
            price = latest_price(p["ticker"]) or p["entry_price"]
        side = (p.get("side") or "LONG").upper()
        qty = p["quantity"]
        entry = p["entry_price"]
        if side == "SHORT":
            equity += entry * qty                 # margin block returned on cover
            unreal += (entry - price) * qty       # short profit when price drops
        else:
            equity += price * qty
            unreal += (price - entry) * qty
    return equity, unreal, len(positions)


def _snapshot_row(cash: float, prices: Dict[str, float] | None = None) -> dict:
    """Compute equity + write a new snapshot row. Returns the written row as dict."""
    equity, unreal, n = _current_equity(prices)
    realized = realized_pnl_total()
    total = cash + equity
    ts = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO portfolio_snapshots
               (ts, cash, equity, total_value, unrealized_pnl, realized_pnl, open_positions)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ts, cash, equity, total, unreal, realized, n),
        )
    return dict(ts=ts, cash=cash, equity=equity, total_value=total,
                unrealized_pnl=unreal, realized_pnl=realized, open_positions=n)


def snapshot(prices: Dict[str, float] | None = None) -> dict:
    """Write a fresh snapshot at the current cash level and return it."""
    return _snapshot_row(get_cash(), prices)


def snapshots_df():
    import pandas as pd
    df = query_df("SELECT * FROM portfolio_snapshots ORDER BY ts")
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], format="mixed", utc=True)
    return df


def trades_df():
    import pandas as pd
    df = query_df("SELECT * FROM trades ORDER BY ts DESC")
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], format="mixed", utc=True)
    return df

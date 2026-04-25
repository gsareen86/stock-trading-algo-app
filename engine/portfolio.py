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
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) AS total FROM positions WHERE status='CLOSED'"
        ).fetchone()
    return float(row["total"])


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
                  prices: Dict[str, float] | None = None) -> Optional[int]:
    """Place a BUY (long-only for v1) and register the position."""
    cash = get_cash()
    exec_ = execute("BUY", price, quantity)
    cost = -exec_.net  # exec_.net is negative on BUY (cash out)
    if cost > cash:
        log.warning("insufficient cash for %s qty=%d cost=%.2f cash=%.2f",
                    ticker, quantity, cost, cash)
        return None

    now = datetime.utcnow().isoformat()
    # Commit the position + trade first...
    with get_conn() as conn:
        position_id = insert_returning_id(
            conn,
            """INSERT INTO positions
               (ticker, entry_ts, entry_price, quantity, stop_loss, take_profit,
                strategy, composite_score, status)
               VALUES (?,?,?,?,?,?,?,?, 'OPEN')""",
            (ticker, now, exec_.fill_price, quantity, stop_loss, take_profit,
             strategy, composite_score),
        )
        conn.execute(
            """INSERT INTO trades
               (ts, ticker, side, quantity, price, value, costs, net_value,
                strategy, reason, composite_score, mode, position_id)
               VALUES (?,?, 'BUY', ?,?,?,?,?,?,?,?,?,?)""",
            (now, ticker, quantity, exec_.fill_price, exec_.gross,
             exec_.total_costs, exec_.net, strategy, reason, composite_score,
             mode, position_id),
        )

    # ...then write the snapshot with the committed state visible
    new_cash = cash + exec_.net  # net is negative on BUY
    _snapshot_row(new_cash, prices=prices or {ticker: exec_.fill_price})

    log.info("OPEN %s %d @ %.2f cost=%.2f", ticker, quantity, exec_.fill_price, -exec_.net)
    return position_id


def close_position(position_id: int, price: float, *, reason: str = "",
                   mode: str = "auto") -> Optional[float]:
    """Close an open position. Returns realized P&L (after costs), or None if not found."""
    with get_conn() as conn:
        pos = conn.execute(
            "SELECT * FROM positions WHERE id=? AND status='OPEN'", (position_id,)
        ).fetchone()
        if not pos:
            return None
        qty = pos["quantity"]
        entry = pos["entry_price"]
        ticker = pos["ticker"]

    exec_ = execute("SELL", price, qty)
    proceeds = exec_.net
    entry_cost = entry * qty  # approximate: entry costs were already deducted on BUY
    pnl = proceeds - entry_cost
    pnl_pct = (pnl / entry_cost) * 100 if entry_cost else 0

    now = datetime.utcnow().isoformat()
    # Commit the close first...
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
               VALUES (?,?, 'SELL', ?,?,?,?,?,?,?,?,?,?)""",
            (now, ticker, qty, exec_.fill_price, exec_.gross,
             exec_.total_costs, exec_.net, pos["strategy"], reason,
             pos["composite_score"], mode, position_id),
        )

    # ...then write snapshot (sees committed state)
    new_cash = get_cash() + exec_.net
    _snapshot_row(new_cash)

    log.info("CLOSE %s qty=%d @ %.2f PnL=%.2f (%+.2f%%) [%s]",
             ticker, qty, exec_.fill_price, pnl, pnl_pct, reason)
    return pnl


# ---------- Snapshots ----------


def _current_equity(prices: Dict[str, float] | None = None) -> tuple[float, float, int]:
    """Return (equity_value, unrealized_pnl, open_count) for open positions."""
    equity = 0.0
    unreal = 0.0
    positions = open_positions()  # reads committed state via fresh connection
    for p in positions:
        price = (prices or {}).get(p["ticker"])
        if not price:
            price = latest_price(p["ticker"]) or p["entry_price"]
        equity += price * p["quantity"]
        unreal += (price - p["entry_price"]) * p["quantity"]
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
        df["ts"] = pd.to_datetime(df["ts"])
    return df


def trades_df():
    import pandas as pd
    df = query_df("SELECT * FROM trades ORDER BY ts DESC")
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
    return df

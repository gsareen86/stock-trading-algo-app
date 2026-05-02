"""
Performance analytics: equity curve stats, Sharpe/Sortino, max drawdown, win rate,
strategy breakdown, benchmark comparison vs NIFTY 50.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

from config import BENCHMARK_TICKER, INITIAL_CAPITAL
from data.fetcher import fetch_candles
from engine.portfolio import snapshots_df, trades_df


# ---------- Return stats ----------


def _returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def sharpe_ratio(returns: pd.Series, rf: float = 0.0, periods_per_year: int = 252) -> float:
    if returns is None or returns.empty:
        return 0.0
    std = float(returns.std())
    if std != std:  # NaN — insufficient data
        log.debug("sharpe_ratio: std is NaN, returning 0.0")
        return 0.0
    if not std:     # zero volatility — ratio undefined
        return 0.0
    excess = returns - rf / periods_per_year
    val = np.sqrt(periods_per_year) * excess.mean() / std
    if val != val:  # NaN from mean()
        log.debug("sharpe_ratio: result is NaN, returning 0.0")
        return 0.0
    return float(val)


def sortino_ratio(returns: pd.Series, rf: float = 0.0, periods_per_year: int = 252) -> float:
    if returns is None or returns.empty:
        return 0.0
    downside = returns[returns < 0]
    dstd = float(downside.std()) if not downside.empty else 0.0
    if dstd != dstd:  # NaN — insufficient downside data
        log.debug("sortino_ratio: downside std is NaN, returning 0.0")
        return 0.0
    if not dstd:      # no losing periods — ratio undefined (positive infinity)
        return 0.0
    excess = float(returns.mean()) - rf / periods_per_year
    val = np.sqrt(periods_per_year) * excess / dstd
    if val != val:
        log.debug("sortino_ratio: result is NaN, returning 0.0")
        return 0.0
    return float(val)


def max_drawdown(equity: pd.Series) -> float:
    if equity is None or equity.empty:
        return 0.0
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax.replace(0, np.nan)
    val = dd.min()
    if val != val:
        return 0.0
    return float(val)


# ---------- Trade stats ----------


# ---------- Per-position P&L (canonical) ----------
#
# WHY THIS HELPER EXISTS — the previous trade_stats() merged BUYs to SELLs by
# position_id and computed P&L per *row pair*. That broke catastrophically once
# we added partial-T1 exits (which write a *second* SELL row for the same
# position_id) and SHORT positions (which use side='SHORT'/'COVER' instead of
# 'BUY'/'SELL'). The fix: don't pair rows at all — just sum every trade row's
# net_value, grouped by position_id. Cash-flow truth wins:
#
#   LONG  BUY  net_value = -(entry*qty + costs)
#   LONG  SELL net_value = +(exit*qty  - costs)            sum = pnl
#   SHORT      net_value = -(entry*qty + costs)
#   COVER      net_value = +(entry*qty + pnl)              sum = pnl
#
# Any partial-T1 exits become additional positive net_value rows. Summing them
# all gives the true realised P&L for the position regardless of how many legs.

def _per_position_pnl() -> pd.DataFrame:
    """Return one row per FULLY-CLOSED position with summed cash-flow P&L.

    Columns: position_id, ticker, side, strategy, opened_at, closed_at, pnl,
    qty, entry_price, exit_price.
    """
    df = trades_df()
    if df.empty:
        return pd.DataFrame()

    open_sides  = df["side"].isin(["BUY", "SHORT"])
    close_sides = df["side"].isin(["SELL", "COVER"])

    # Sum net_value per position — that's the realised P&L from cash flow.
    pnl_by_pos = (
        df.groupby("position_id")["net_value"].sum()
        .rename("pnl").reset_index()
    )

    # Position is "fully closed" only if its open leg has at least one
    # matching close leg AND the positions table marks it CLOSED. We don't
    # have access to positions table here, so use the heuristic: total qty
    # closed >= qty opened. Good enough — partial-closed positions get
    # excluded so we don't show running P&L as final.
    qty_open  = df[open_sides ].groupby("position_id")["quantity"].sum().rename("qty_opened")
    qty_close = df[close_sides].groupby("position_id")["quantity"].sum().rename("qty_closed")
    qty = pd.concat([qty_open, qty_close], axis=1).fillna(0)
    fully_closed = qty[qty["qty_closed"] >= qty["qty_opened"]].index

    pnl_by_pos = pnl_by_pos[pnl_by_pos["position_id"].isin(fully_closed)]
    if pnl_by_pos.empty:
        return pd.DataFrame()

    # Pull metadata from the OPEN-side row (one per position).
    open_meta = (
        df[open_sides].sort_values("ts")
        .drop_duplicates("position_id", keep="first")
        [["position_id", "ticker", "side", "strategy", "ts", "price"]]
        .rename(columns={"ts": "opened_at", "price": "entry_price",
                         "side": "open_side"})
    )
    # Map open_side -> position direction.
    open_meta["direction"] = open_meta["open_side"].map(
        {"BUY": "LONG", "SHORT": "SHORT"}
    )

    # Final close ts + price (use the LATEST close-side row).
    close_meta = (
        df[close_sides].sort_values("ts")
        .drop_duplicates("position_id", keep="last")
        [["position_id", "ts", "price"]]
        .rename(columns={"ts": "closed_at", "price": "exit_price"})
    )

    out = pnl_by_pos.merge(open_meta, on="position_id", how="left")
    out = out.merge(close_meta, on="position_id", how="left")
    out = out.merge(qty["qty_opened"].rename("qty").reset_index(),
                    on="position_id", how="left")
    return out[[
        "position_id", "opened_at", "closed_at", "ticker", "direction",
        "qty", "entry_price", "exit_price", "pnl", "strategy",
    ]].sort_values("closed_at", ascending=False).reset_index(drop=True)


def trade_stats() -> Dict:
    """Aggregate stats over all FULLY-CLOSED positions (LONG + SHORT)."""
    pos = _per_position_pnl()
    if pos.empty:
        return dict(total_trades=0)
    pnl = pos["pnl"]
    wins = pos[pnl > 0]
    losses = pos[pnl <= 0]
    win_rate = len(wins) / len(pos) if len(pos) else 0
    avg_win = wins["pnl"].mean() if len(wins) else 0
    avg_loss = losses["pnl"].mean() if len(losses) else 0
    pf = (
        wins["pnl"].sum() / abs(losses["pnl"].sum())
        if len(losses) and losses["pnl"].sum() != 0
        else float("inf") if len(wins) else 0
    )
    return dict(
        total_trades=len(pos),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(win_rate * 100, 2),
        avg_win=round(float(avg_win), 2),
        avg_loss=round(float(avg_loss), 2),
        total_pnl=round(float(pnl.sum()), 2),
        profit_factor=round(float(pf), 2) if pf != float("inf") else "∞",
        best_trade=round(float(pnl.max()), 2),
        worst_trade=round(float(pnl.min()), 2),
    )


def strategy_breakdown() -> pd.DataFrame:
    """PnL + counts grouped by strategy — both directions, partial-close-safe."""
    pos = _per_position_pnl()
    if pos.empty:
        return pd.DataFrame()
    grp = pos.groupby("strategy").agg(
        trades=("pnl", "count"),
        total_pnl=("pnl", "sum"),
        avg_pnl=("pnl", "mean"),
        wins=("pnl", lambda x: (x > 0).sum()),
    ).reset_index()
    grp["win_rate_pct"] = round(grp["wins"] / grp["trades"] * 100, 2)
    return grp.round(2)


def closed_positions_report(start_date=None, end_date=None) -> pd.DataFrame:
    """Per-trade P&L report with optional date filter on closed_at (UTC)."""
    pos = _per_position_pnl()
    if pos.empty:
        return pos
    if start_date is not None:
        pos = pos[pd.to_datetime(pos["closed_at"]) >= pd.to_datetime(start_date)]
    if end_date is not None:
        pos = pos[pd.to_datetime(pos["closed_at"]) <= pd.to_datetime(end_date)]
    return pos.reset_index(drop=True)


# ---------- Portfolio summary ----------


def portfolio_summary() -> Dict:
    snaps = snapshots_df()
    if snaps.empty:
        return dict(
            total_value=INITIAL_CAPITAL, cash=INITIAL_CAPITAL, equity=0,
            total_return_pct=0, unrealized_pnl=0, realized_pnl=0,
            sharpe=0, sortino=0, max_dd_pct=0,
        )

    last = snaps.iloc[-1]
    equity_curve = snaps.set_index("ts")["total_value"]
    returns = _returns(equity_curve)

    return dict(
        total_value=round(float(last["total_value"]), 2),
        cash=round(float(last["cash"]), 2),
        equity=round(float(last["equity"]), 2),
        unrealized_pnl=round(float(last["unrealized_pnl"]), 2),
        realized_pnl=round(float(last["realized_pnl"]), 2),
        total_return_pct=round(
            (last["total_value"] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2
        ),
        sharpe=round(sharpe_ratio(returns), 3),
        sortino=round(sortino_ratio(returns), 3),
        max_dd_pct=round(max_drawdown(equity_curve) * 100, 2),
        snapshots=len(snaps),
    )


# ---------- Benchmark ----------


def benchmark_series(days: int = 30) -> Optional[pd.Series]:
    df = fetch_candles(BENCHMARK_TICKER, interval="1d", days=days)
    if df.empty:
        return None
    return df["Close"]

"""
Performance analytics: equity curve stats, Sharpe/Sortino, max drawdown, win rate,
strategy breakdown, benchmark comparison vs NIFTY 50.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

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
    if not std or std != std:  # 0 or NaN
        return 0.0
    excess = returns - rf / periods_per_year
    val = np.sqrt(periods_per_year) * excess.mean() / std
    if val != val:
        return 0.0
    return float(val)


def sortino_ratio(returns: pd.Series, rf: float = 0.0, periods_per_year: int = 252) -> float:
    if returns is None or returns.empty:
        return 0.0
    downside = returns[returns < 0]
    dstd = float(downside.std()) if not downside.empty else 0.0
    if not dstd or dstd != dstd:  # 0 or NaN
        return 0.0
    excess = float(returns.mean()) - rf / periods_per_year
    val = np.sqrt(periods_per_year) * excess / dstd
    if val != val:  # NaN
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


def trade_stats() -> Dict:
    df = trades_df()
    if df.empty:
        return dict(total_trades=0)

    # Pair buy/sell per position_id
    sells = df[df["side"] == "SELL"].copy()
    buys = df[df["side"] == "BUY"].copy()
    sells = sells.set_index("position_id")
    buys = buys.set_index("position_id")
    merged = sells.join(buys, lsuffix="_sell", rsuffix="_buy", how="inner")
    if merged.empty:
        return dict(total_trades=0, open_trades=len(buys) - len(sells))

    merged["pnl"] = merged["net_value_sell"] + merged["net_value_buy"]
    wins = merged[merged["pnl"] > 0]
    losses = merged[merged["pnl"] <= 0]

    win_rate = len(wins) / len(merged) if len(merged) else 0
    avg_win = wins["pnl"].mean() if len(wins) else 0
    avg_loss = losses["pnl"].mean() if len(losses) else 0
    profit_factor = (
        wins["pnl"].sum() / abs(losses["pnl"].sum()) if len(losses) and losses["pnl"].sum() != 0
        else float("inf") if len(wins) else 0
    )

    return dict(
        total_trades=len(merged),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(win_rate * 100, 2),
        avg_win=round(float(avg_win), 2),
        avg_loss=round(float(avg_loss), 2),
        total_pnl=round(float(merged["pnl"].sum()), 2),
        profit_factor=round(float(profit_factor), 2) if profit_factor != float("inf") else "∞",
        best_trade=round(float(merged["pnl"].max()), 2),
        worst_trade=round(float(merged["pnl"].min()), 2),
    )


def strategy_breakdown() -> pd.DataFrame:
    """PnL + counts grouped by strategy."""
    df = trades_df()
    if df.empty:
        return pd.DataFrame()
    sells = df[df["side"] == "SELL"]
    buys = df[df["side"] == "BUY"]
    merged = sells.merge(buys, on="position_id", suffixes=("_sell", "_buy"))
    if merged.empty:
        return pd.DataFrame()
    merged["pnl"] = merged["net_value_sell"] + merged["net_value_buy"]
    grp = merged.groupby("strategy_buy").agg(
        trades=("pnl", "count"),
        total_pnl=("pnl", "sum"),
        avg_pnl=("pnl", "mean"),
        wins=("pnl", lambda x: (x > 0).sum()),
    ).reset_index().rename(columns={"strategy_buy": "strategy"})
    grp["win_rate_pct"] = round(grp["wins"] / grp["trades"] * 100, 2)
    return grp.round(2)


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

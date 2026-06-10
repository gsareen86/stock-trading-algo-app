"""
Walk-forward EOD backtester for the positional swing book (Phase 5).

Simulates the live engine's rules on historical daily candles:

  Signals   : positional.scanner.scan_ticker (Minervini trend template + VCP)
              evaluated point-in-time on each day's data slice.
  Sizing    : risk-based (risk_pct of pool / distance to the hard stop),
              capped at max_position_pct — same maths as live.
  Exits     : hard stop → +2R partial (stop to breakeven) → 21-EMA
              double-close trail → time stop. Evaluated on closes, like the
              live EOD checks.
  Costs     : the real delivery cost model + slippage on every fill.

Honest limitations (documented, not hidden):
  * Technical-only — quality/sentiment/management pillars and the LLM veto
    depend on DB state that has no historical snapshot, so the backtest
    validates the TIMING layer and the exit/sizing rules, not the full
    composite.
  * Close-fills — stops execute at the day's close (the live engine also
    checks at EOD), so intraday gap-throughs fill at the close, which can
    flatter results in crashes.

Usage:
    from backtest.engine import load_price_data, run_backtest, walk_forward, BTConfig
    data = load_price_data(["RELIANCE", "TCS", ...], years=3)
    res  = run_backtest(data, cfg=BTConfig())
    wf   = walk_forward(data, param_grid={"min_trend_score": [55, 60, 67]})

CLI:
    python -m backtest.engine --tickers RELIANCE,TCS,INFY --years 3
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict, replace
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

@dataclass
class BTConfig:
    capital: float = 100_000.0
    max_positions: int = 5
    max_position_pct: float = 0.20
    use_risk_sizing: bool = True
    risk_pct: float = 0.01            # of pool, per trade
    hard_stop_pct: float = 0.08
    partial_at_r: float = 2.0
    partial_fraction: float = 0.50
    ema_trail_period: int = 21
    ema_trail_consecutive: int = 2
    time_stop_days: int = 15          # trading days
    time_stop_min_move_pct: float = 2.0
    min_trend_score: float = 60.0
    scan_every_n_days: int = 1        # >1 trades signal latency for speed
    min_history_days: int = 230       # scan_ticker needs 220+ rows


@dataclass
class BTTrade:
    ticker: str
    side: str                 # BUY / SELL
    dt: str
    qty: int
    price: float
    costs: float
    pnl: float
    reason: str


@dataclass
class BTResult:
    config: dict
    start: str
    end: str
    n_days: int
    trades: List[BTTrade] = field(default_factory=list)
    equity_curve: List[Tuple[str, float]] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        return (f"{self.start}→{self.end}  trades={m.get('n_round_trips', 0)} "
                f"ret={m.get('total_return_pct', 0):+.1f}% "
                f"sharpe={m.get('sharpe', 0):.2f} maxDD={m.get('max_dd_pct', 0):.1f}% "
                f"win={m.get('win_rate_pct', 0):.0f}% pf={m.get('profit_factor', 0):.2f}")


class _OpenPos:
    __slots__ = ("ticker", "entry_idx", "entry", "qty", "initial_qty",
                 "stop", "partial_done", "below_ema", "peak")

    def __init__(self, ticker, entry_idx, entry, qty, stop):
        self.ticker = ticker
        self.entry_idx = entry_idx
        self.entry = entry
        self.qty = qty
        self.initial_qty = qty
        self.stop = stop
        self.partial_done = False
        self.below_ema = 0
        self.peak = entry


# ── Data loading ─────────────────────────────────────────────────────────────

def load_price_data(tickers: List[str], years: int = 3) -> Dict[str, pd.DataFrame]:
    """Daily OHLCV per ticker via the parquet-cached fetcher."""
    from data.fetcher import fetch_candles
    out: Dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            df = fetch_candles(t, interval="1d", days=int(years * 365) + 30)
            if df is not None and len(df) > 0:
                out[t] = df
        except Exception as e:
            log.warning("[backtest] data load failed for %s: %s", t, e)
    return out


# ── Cost model (reuses the live delivery model) ──────────────────────────────

def _fill(side: str, price: float, qty: int) -> Tuple[float, float]:
    """(fill_price_after_slippage, total_costs)."""
    from positional.risk import compute_delivery_costs, delivery_fill_price
    fp = delivery_fill_price(side, price)
    return fp, compute_delivery_costs(side, fp, qty)


# ── Core simulation ──────────────────────────────────────────────────────────

def _close_series(df: pd.DataFrame) -> pd.Series:
    s = df["Close"].astype(float)
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s[~s.index.duplicated(keep="last")]


def run_backtest(price_data: Dict[str, pd.DataFrame],
                 cfg: Optional[BTConfig] = None,
                 start: Optional[str] = None,
                 end: Optional[str] = None) -> BTResult:
    """Event-driven daily simulation over the union of trading days."""
    import positional.scanner as scanner

    cfg = cfg or BTConfig()
    closes = {t: _close_series(df) for t, df in price_data.items()}
    frames = {}
    for t, df in price_data.items():
        f = df.copy()
        f.index = pd.to_datetime(f.index).tz_localize(None).normalize()
        frames[t] = f[~f.index.duplicated(keep="last")]

    all_days = sorted(set().union(*[set(s.index) for s in closes.values()]))
    if start:
        all_days = [d for d in all_days if d >= pd.Timestamp(start)]
    if end:
        all_days = [d for d in all_days if d <= pd.Timestamp(end)]
    if not all_days:
        return BTResult(config=asdict(cfg), start=str(start), end=str(end),
                        n_days=0, metrics={"error": "no trading days in range"})

    cash = cfg.capital
    open_pos: Dict[str, _OpenPos] = {}
    trades: List[BTTrade] = []
    equity_curve: List[Tuple[str, float]] = []
    wins: List[float] = []
    losses: List[float] = []
    hold_days: List[int] = []
    entry_costs: Dict[str, float] = {}   # ticker -> cumulative entry cash out
    realized: Dict[str, float] = {}      # ticker -> cumulative cash back in

    def _book_exit(t: str, day_i: int, dstr: str, px: float, qty: int, reason: str,
                   pos: _OpenPos, full: bool) -> None:
        nonlocal cash
        fp, costs = _fill("SELL", px, qty)
        proceeds = fp * qty - costs
        cash += proceeds
        pnl = (fp - pos.entry) * qty - costs
        trades.append(BTTrade(t, "SELL", dstr, qty, round(fp, 2),
                              round(costs, 2), round(pnl, 2), reason))
        realized[t] = realized.get(t, 0.0) + proceeds
        if full:
            total_pnl = realized[t] - entry_costs.get(t, 0.0)
            (wins if total_pnl > 0 else losses).append(total_pnl)
            hold_days.append(day_i - pos.entry_idx)
            del open_pos[t]
            entry_costs.pop(t, None)
            realized.pop(t, None)
        else:
            pos.qty -= qty

    for day_i, day in enumerate(all_days):
        dstr = day.strftime("%Y-%m-%d")

        # ── 1. Manage open positions (close-based, like live EOD checks) ──
        for t in list(open_pos):
            pos = open_pos[t]
            s = closes.get(t)
            if s is None or day not in s.index:
                continue
            px = float(s.loc[day])
            if not math.isfinite(px) or px <= 0:
                continue
            pos.peak = max(pos.peak, px)

            # 1a. partial at +R multiple
            if not pos.partial_done:
                r = pos.entry - pos.stop
                if r > 0 and px >= pos.entry + cfg.partial_at_r * r:
                    sell_qty = int(pos.qty * cfg.partial_fraction)
                    if 0 < sell_qty < pos.qty:
                        _book_exit(t, day_i, dstr, px, sell_qty,
                                   "PARTIAL_2R", pos, full=False)
                        pos.partial_done = True
                        pos.stop = pos.entry  # breakeven

            # 1b. hard stop
            if px <= pos.stop:
                _book_exit(t, day_i, dstr, px, pos.qty, "HARD_STOP", pos, full=True)
                continue

            # 1c. EMA trail (double close below)
            hist = s.loc[:day]
            if len(hist) >= cfg.ema_trail_period + cfg.ema_trail_consecutive:
                ema = hist.ewm(span=cfg.ema_trail_period, adjust=False).mean()
                below = (hist < ema).tolist()
                consec = 0
                for flag in reversed(below):
                    if flag:
                        consec += 1
                    else:
                        break
                pos.below_ema = consec
                if consec >= cfg.ema_trail_consecutive:
                    _book_exit(t, day_i, dstr, px, pos.qty, "EMA_TRAIL", pos, full=True)
                    continue

            # 1d. time stop
            if (day_i - pos.entry_idx) >= cfg.time_stop_days:
                max_move = (pos.peak - pos.entry) / pos.entry * 100
                if max_move < cfg.time_stop_min_move_pct:
                    _book_exit(t, day_i, dstr, px, pos.qty, "TIME_STOP", pos, full=True)
                    continue

        # ── 2. Entries ──
        if day_i % cfg.scan_every_n_days == 0 and len(open_pos) < cfg.max_positions:
            signals = []
            for t, f in frames.items():
                if t in open_pos:
                    continue
                hist = f.loc[:day]
                if len(hist) < cfg.min_history_days:
                    continue
                try:
                    res = scanner.scan_ticker(t, hist)
                except Exception:
                    res = None
                if (res and res.get("trend_template")
                        and float(res.get("score") or 0) >= cfg.min_trend_score):
                    signals.append(res)
            signals.sort(key=lambda r: r["score"], reverse=True)

            for sig in signals:
                if len(open_pos) >= cfg.max_positions:
                    break
                t = sig["ticker"]
                px = float(sig["price"])
                stop = px * (1 - cfg.hard_stop_pct)
                if cfg.use_risk_sizing:
                    risk_amount = cfg.capital * cfg.risk_pct
                    qty = int(risk_amount / max(px - stop, 1e-9))
                else:
                    qty = int((cfg.capital / cfg.max_positions) / px)
                qty = min(qty, int(cfg.capital * cfg.max_position_pct / px),
                          int(cash / px) if px > 0 else 0)
                if qty <= 0:
                    continue
                fp, costs = _fill("BUY", px, qty)
                outlay = fp * qty + costs
                if outlay > cash:
                    continue
                cash -= outlay
                open_pos[t] = _OpenPos(t, day_i, fp, qty, fp * (1 - cfg.hard_stop_pct))
                entry_costs[t] = entry_costs.get(t, 0.0) + outlay
                trades.append(BTTrade(t, "BUY", dstr, qty, round(fp, 2),
                                      round(costs, 2), 0.0, f"score={sig['score']:.0f}"))

        # ── 3. Mark to market ──
        mtm = cash
        for t, pos in open_pos.items():
            s = closes.get(t)
            if s is not None:
                h = s.loc[:day]
                if len(h):
                    mtm += float(h.iloc[-1]) * pos.qty
        equity_curve.append((dstr, round(mtm, 2)))

    return BTResult(
        config=asdict(cfg),
        start=all_days[0].strftime("%Y-%m-%d"),
        end=all_days[-1].strftime("%Y-%m-%d"),
        n_days=len(all_days),
        trades=trades,
        equity_curve=equity_curve,
        metrics=_metrics(cfg, equity_curve, wins, losses, hold_days),
    )


def _metrics(cfg: BTConfig, equity_curve, wins, losses, hold_days) -> dict:
    if not equity_curve:
        return {}
    eq = pd.Series([v for _, v in equity_curve],
                   index=pd.to_datetime([d for d, _ in equity_curve]))
    total_ret = (float(eq.iloc[-1]) - cfg.capital) / cfg.capital * 100
    yrs = max(len(eq) / 252.0, 1e-9)
    cagr = ((float(eq.iloc[-1]) / cfg.capital) ** (1 / yrs) - 1) * 100 \
        if eq.iloc[-1] > 0 else -100.0
    rets = eq.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * (252 ** 0.5)) \
        if len(rets) > 1 and float(rets.std()) > 0 else 0.0
    dd = ((eq - eq.cummax()) / eq.cummax()).min()
    n_rt = len(wins) + len(losses)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "total_return_pct": round(total_ret, 2),
        "cagr_pct": round(cagr, 2),
        "sharpe": round(sharpe, 2),
        "max_dd_pct": round(float(dd) * 100, 2),
        "n_round_trips": n_rt,
        "win_rate_pct": round(100.0 * len(wins) / n_rt, 1) if n_rt else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else
                         (float("inf") if gross_win > 0 else 0.0),
        "avg_hold_days": round(sum(hold_days) / len(hold_days), 1) if hold_days else 0.0,
        "final_equity": round(float(eq.iloc[-1]), 2),
    }


# ── Walk-forward harness ─────────────────────────────────────────────────────

def _month_edges(days: List[pd.Timestamp], months: int) -> List[pd.Timestamp]:
    """Split a sorted day list into edges roughly `months` apart."""
    if not days:
        return []
    edges = [days[0]]
    cur = days[0]
    for d in days:
        if (d.year - cur.year) * 12 + (d.month - cur.month) >= months:
            edges.append(d)
            cur = d
    if edges[-1] != days[-1]:
        edges.append(days[-1])
    return edges


def walk_forward(price_data: Dict[str, pd.DataFrame],
                 param_grid: Optional[Dict[str, list]] = None,
                 train_months: int = 6,
                 test_months: int = 3,
                 base_cfg: Optional[BTConfig] = None) -> dict:
    """Anchored walk-forward: on each fold, pick the param combo with the
    best train-window Sharpe, then evaluate it out-of-sample on the next
    test window. Reports per-fold results + the stitched out-of-sample
    aggregate — the number that matters."""
    base_cfg = base_cfg or BTConfig()
    param_grid = param_grid or {"min_trend_score": [55.0, 60.0, 67.0]}

    closes = {t: _close_series(df) for t, df in price_data.items()}
    all_days = sorted(set().union(*[set(s.index) for s in closes.values()]))
    if len(all_days) < 300:
        return {"error": f"need ≥300 trading days, have {len(all_days)}"}

    # Build parameter combos (cartesian product).
    import itertools
    keys = list(param_grid)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*param_grid.values())]

    step = test_months
    edges = _month_edges(all_days, step)
    folds = []
    oos_curve: List[Tuple[str, float]] = []
    oos_wins: List[float] = []
    oos_losses: List[float] = []
    capital = base_cfg.capital

    fold_start_i = 0
    while True:
        # train window = train_months before the test window
        test_start_idx = fold_start_i + 1
        if test_start_idx + 1 > len(edges) - 1:
            break
        train_end = edges[test_start_idx]
        train_start = train_end - pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = edges[min(test_start_idx + 1, len(edges) - 1)]
        if test_end <= test_start:
            break

        # pick best combo on the train window
        best_combo, best_sharpe = None, -1e9
        for combo in combos:
            cfg = replace(base_cfg, **combo)
            r = run_backtest(price_data, cfg=cfg,
                             start=train_start.strftime("%Y-%m-%d"),
                             end=train_end.strftime("%Y-%m-%d"))
            s = r.metrics.get("sharpe", -1e9)
            if s > best_sharpe:
                best_sharpe, best_combo = s, combo

        # evaluate out-of-sample
        cfg = replace(base_cfg, **(best_combo or {}))
        r = run_backtest(price_data, cfg=cfg,
                         start=test_start.strftime("%Y-%m-%d"),
                         end=test_end.strftime("%Y-%m-%d"))
        folds.append({
            "train": f"{train_start.date()}→{train_end.date()}",
            "test": f"{test_start.date()}→{test_end.date()}",
            "chosen_params": best_combo,
            "train_sharpe": round(best_sharpe, 2),
            "test_metrics": r.metrics,
        })
        # stitch the OOS equity (rebase each fold onto the running capital)
        if r.equity_curve:
            scale = capital / base_cfg.capital
            for dstr, v in r.equity_curve:
                oos_curve.append((dstr, round(v * scale, 2)))
            capital = oos_curve[-1][1]
        fold_start_i = test_start_idx

    oos_metrics = {}
    if oos_curve:
        eq = pd.Series([v for _, v in oos_curve],
                       index=pd.to_datetime([d for d, _ in oos_curve]))
        rets = eq.pct_change().dropna()
        oos_metrics = {
            "total_return_pct": round((float(eq.iloc[-1]) / base_cfg.capital - 1) * 100, 2),
            "sharpe": round(float(rets.mean() / rets.std() * (252 ** 0.5)), 2)
                      if len(rets) > 1 and float(rets.std()) > 0 else 0.0,
            "max_dd_pct": round(float(((eq - eq.cummax()) / eq.cummax()).min()) * 100, 2),
            "n_folds": len(folds),
        }

    return {"folds": folds, "oos": oos_metrics,
            "note": ("Out-of-sample (oos) numbers are the ones to trust; "
                     "train-window Sharpe is in-sample and inflated.")}


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Positional swing-book backtester")
    ap.add_argument("--tickers", type=str, default="",
                    help="Comma-separated NSE tickers; default: pos_universe")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--walk-forward", action="store_true")
    ap.add_argument("--min-score", type=float, default=60.0)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO)
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        from positional.universe import get_fundamental_universe
        tickers = get_fundamental_universe()[:30]
    if not tickers:
        print("No tickers — pass --tickers or populate pos_universe first.")
        return

    print(f"Loading {len(tickers)} tickers ({args.years}y daily)...")
    data = load_price_data(tickers, years=args.years)
    print(f"Loaded {len(data)} tickers with data.")
    if args.walk_forward:
        wf = walk_forward(data)
        import json
        print(json.dumps(wf, indent=2, default=str))
    else:
        res = run_backtest(data, cfg=BTConfig(min_trend_score=args.min_score))
        print(res.summary())
        for k, v in res.metrics.items():
            print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()

"""Long replays, from a terminal.

A five-year replay of the Nifty 500 is hours of strategy evaluation — a job, not a request.
This runs it with every core, prints one summary per strategy, and writes the whole report and
every trade to files you can open in a spreadsheet::

    python -m app.backtest.cli --start 2021-01-01 --index NIFTY500 --workers 8 \\
        --out backtest.json --trades trades.csv

Prices come through the same parquet cache the app uses, so a second run is fast. Each
strategy is reported alone; there is no combined line, for the reason `runner` gives.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from app.backtest.runner import (
    DEFAULT_ROUND_TRIP_COST_PCT,
    DEFAULT_SLIPPAGE_BPS,
    BacktestConfig,
    run,
    symbols_with_sectors,
)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.backtest.cli", description=(__doc__ or "").split("\n")[0]
    )
    p.add_argument("--start", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    p.add_argument("--end", type=date.fromisoformat, default=None, help="YYYY-MM-DD (today)")
    p.add_argument("--index", default="NIFTY500", help="NIFTY500 or NIFTY_TOTAL_MARKET")
    p.add_argument("--symbols", default="", help="comma-separated subset of the index")
    p.add_argument("--limit", type=int, default=0, help="first N names of the index only")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--step", type=int, default=5, help="evaluate every Nth session")
    p.add_argument("--entry-mode", choices=("plan", "next_open"), default="plan")
    p.add_argument("--max-hold", type=int, default=120, help="sessions")
    p.add_argument("--order-valid", type=int, default=10, help="sessions a buy-stop stays live")
    p.add_argument("--max-chase", type=float, default=5.0, help="%% above entry still bought")
    p.add_argument("--cost", type=float, default=DEFAULT_ROUND_TRIP_COST_PCT, help="round trip %%")
    p.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    p.add_argument("--benchmark", default="^CRSLDX")
    p.add_argument("--no-fundamentals", action="store_true",
                   help="skip quarterly results (fun_tech_momentum then cannot assess)")
    p.add_argument("--out", type=Path, default=Path("backtest-report.json"))
    p.add_argument("--trades", type=Path, default=Path("backtest-trades.csv"))
    return p


def _fmt(value, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def _summary(body: dict) -> str:
    lines = [
        f"{body['sessions']} sessions, {body['evaluations']} evaluations, "
        f"{len(body['config']['symbols'])} symbols "
        f"({body['config']['sectors_known']} with a sector)",
        "",
    ]
    for sid, result in body["results"].items():
        perf = result["performance"]
        lines.append(f"== {sid}")
        lines.append(
            f"   BUY signals {result['buy_signals']}  orders {result['orders_placed']}  "
            f"filled {result['orders_filled']}  extended {result['skipped_extended']}  "
            f"invalidated {result['orders_invalidated']}  expired {result['orders_expired']}  "
            f"no plan {result['buy_without_plan']}"
        )
        if not perf.get("closed"):
            lines.append("   no closed trades")
            continue
        se = perf.get("net_excess_se_pp")
        lines.append(
            f"   trades {perf['closed']}{'  (THIN)' if perf['thin'] else ''}  "
            f"win {_fmt(perf['win_rate_pct'], '%')}  "
            f"mean net {_fmt(perf['mean_net_return_pct'], '%')}  "
            f"median net {_fmt(perf['median_net_return_pct'], '%')}  "
            f"PF {_fmt(perf['profit_factor'])}  R {_fmt(perf['mean_r_multiple'])}"
        )
        lines.append(
            f"   vs benchmark: mean net excess {_fmt(perf['mean_net_excess_pp'], ' pp')}"
            f"{f' ± {se} SE' if se is not None else ''}  "
            f"beat {_fmt(perf['beat_benchmark_pct'], '%')}  "
            f"held {_fmt(perf['mean_sessions_held'])} sessions"
        )
        for band in result["by_conviction"]:
            if band.get("closed"):
                lines.append(
                    f"   conviction {band['band']:>7}: {band['closed']:>4} trades  "
                    f"mean net {_fmt(band['mean_net_return_pct'], '%')}  "
                    f"net excess {_fmt(band['mean_net_excess_pp'], ' pp')}"
                )
        lines.append(f"   exits: {result['exit_reasons']}")
    lines += ["", "Notes:", *(f"  - {n}" for n in body["notes"]),
              "Biases:", *(f"  - {b}" for b in body["biases"])]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    from app.core.settings import Settings
    from app.data.cache import CachingPriceSource
    from app.data.calendar import NseCalendar
    from app.data.fundamentals import YFinanceFundamentalsSource
    from app.data.universe import NseUniverseSource, bundled_sectors
    from app.data.yfinance_source import YFinancePriceSource
    from app.strategies.registry import StrategyRegistry

    settings = Settings()
    snapshot = NseUniverseSource(index_name=args.index).snapshot()
    symbols, sectors = symbols_with_sectors(snapshot.instruments)
    sectors = {**bundled_sectors(), **sectors}
    if args.symbols:
        wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        symbols = tuple(wanted)
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"universe {snapshot.index_name} ({snapshot.origin}): {len(symbols)} symbols",
          file=sys.stderr)

    config = BacktestConfig(
        start=args.start,
        end=args.end or date.today(),
        symbols=symbols,
        step_sessions=args.step,
        max_hold_sessions=args.max_hold,
        entry_mode=args.entry_mode,
        order_valid_sessions=args.order_valid,
        max_chase_pct=args.max_chase,
        round_trip_cost_pct=args.cost,
        slippage_bps=args.slippage_bps,
        benchmark=args.benchmark.upper(),
        sectors=sectors,
        workers=args.workers,
    )
    prices = CachingPriceSource(YFinancePriceSource(), cache_dir=settings.llm_cache_dir + "/prices")
    started = time.monotonic()

    def progress(done: int, total: int) -> None:
        elapsed = time.monotonic() - started
        print(f"\r  replayed {done}/{total} symbols  ({elapsed:,.0f}s)", end="", file=sys.stderr)

    report = run(
        config,
        prices,
        StrategyRegistry.discover(),
        NseCalendar(),
        fundamentals_source=None if args.no_fundamentals else YFinanceFundamentalsSource(),
        on_progress=progress,
    )
    print(file=sys.stderr)

    body = report.as_dict()
    args.out.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
    trades = [t.as_dict() for r in report.results.values() for t in r.trades]
    if trades:
        with args.trades.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(trades[0]))
            writer.writeheader()
            writer.writerows(trades)
    print(_summary(body))
    print(f"\nreport: {args.out}   trades: {args.trades if trades else '(none)'}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # required on Windows, where worker processes re-import this module
    raise SystemExit(main())

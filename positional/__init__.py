"""
Positional / Swing Trading Module — Minervini VCP Strategy.

Architecture:
  market_regime.py  — Monthly macro filter (18M Nifty ROC, 20M Smallcap ROC, Gold ratio)
  universe.py       — Fundamental universe from Screener.in CSV (ROCE/ROE/SalesGrowth filter)
  scanner.py        — Daily EOD scan: Minervini Trend Template + VCP detection
  risk.py           — Position sizing (equal weight 1L÷5), 8% hard stop, 21 EMA trailing stop
  alerts.py         — Telegram notifications (BUY alert, SELL alert, EOD summary)
  broker.py         — Broker API abstraction (paper/Sharekhan/Zerodha stubs)
  runner.py         — Daemon: runs EOD scan at 4 PM IST, sends summary at 4:30 PM IST

Capital: POSITIONAL_CAPITAL = ₹1,00,000 (separate from intraday pool)
"""
from positional.runner import run_positional_forever, run_eod_scan, run_exit_checks, run_regime_check
from positional.scanner import get_latest_scan_results
from positional.market_regime import get_latest_regime, compute_market_regime
from positional.universe import get_fundamental_universe, universe_stats, process_screener_csv

__all__ = [
    "run_positional_forever",
    "run_eod_scan",
    "run_exit_checks",
    "run_regime_check",
    "get_latest_scan_results",
    "get_latest_regime",
    "compute_market_regime",
    "get_fundamental_universe",
    "universe_stats",
    "process_screener_csv",
]

"""Long-term investment module.

Phase A focus
-------------
Build a *quality-filtered* universe of NIFTY-500 stocks suitable for
long-horizon (1+ year) and tactical (2-12 week) positions. This package
deliberately has SEPARATE storage (lt_universe / lt_quality tables) and
SEPARATE scoring (5-bucket multi-year scorer) from the intraday module:

  - data/fundamentals.py   -> intraday/swing fundamental score (point-in-time)
  - longterm/quality.py    -> 5-bucket multi-year quality score (this package)

Both can run side-by-side without interfering. The intraday scorer keeps using
yfinance .info snapshots; the long-term scorer pulls multi-year history from
screener.in (FII/DII/promoter pledge are not in yfinance at all).

Public entry points (Phase A):
  - screener_scraper.fetch_company(ticker) -> raw parsed dict
  - universe.build_universe()              -> filter NIFTY 500 to candidates
  - quality.score_company(ticker)          -> 0-100 quality score
  - tasks.run_phase_a(...)                 -> orchestrator (CLI/scheduler)
"""

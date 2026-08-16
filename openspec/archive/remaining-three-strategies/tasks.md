# Tasks: remaining-three-strategies

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: strategies, market-data

## Data seam
- [x] `app/data/fundamentals.py` — `QuarterPoint`, `QuarterlyFundamentals`,
      `FundamentalsSource` protocol, yfinance + static implementations
- [x] `app/data/resources/sector_indices.json` — industry→sector map and index tickers
- [x] `app/data/sectors.py` — resolve an industry string to a sector index

## Indicators
- [x] `to_weekly` — resample daily bars
- [x] `horizontal_range_breakout` — multi-year base plus breakout test
- [x] `consolidation_tightness` — range width over a window
- [x] `find_impulse_leg` — surge of N% over M sessions
- [x] `fib_retracement` — level and observed retracement

## Strategies
- [x] `brahma_vishnu_mahesh/` — BRAHMA regime, VISHNU sector RS, MAHESH breakout
- [x] `fun_tech_momentum/` — surprise OR test, sequential growth, base near highs, volume
- [x] `young_momentum/` — base breakout, impulse, pause with Fib bound, entry trigger

## Tests (offline)
- [x] Fundamentals seam: order, source ref, failure, static source
- [x] Sector resolution incl. unknown industry
- [x] Each new indicator against hand-built series
- [x] BVM: bullish vs bearish regime, sector rank, breakout with and without volume
- [x] Fun-Tech: fundamentals gate, EPS-only pass, revenue-only pass, neither, seasonality
- [x] Young Momentum: shallow pause passes, deep retracement fails, no impulse
- [x] Entry levels informational, no sizing in the verdict
- [x] All four registered; four verdicts for one ticker; no blending anywhere
- [x] Conviction reproducible and in range for each

## Verify & ship
- [x] `pytest`, `ruff`; four verdicts demonstrated on one ticker
- [x] Archive deltas into `openspec/specs/`, move change to `openspec/archive/`
- [x] Commit, push

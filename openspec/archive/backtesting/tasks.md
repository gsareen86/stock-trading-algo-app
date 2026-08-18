# Tasks: backtesting

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: backtesting (new), platform-api (ADDED)

## Point-in-time data
- [x] `app/backtest/asof.py` — `AsOfPriceSource`, a `PriceSource` that truncates to a date
- [x] Strategies unmodified; no opt-out
- [x] Clock steps NSE trading days, not calendar days

## Runner
- [x] `app/backtest/runner.py` — walk sessions, evaluate, act next open
- [x] Fills at the next session's open, never the deciding bar's close
- [x] Positions via the real `Ledger` against in-memory SQLite
- [x] Exit rule declared and applied consistently
- [x] Bounded by explicit limits on names, days and evaluations

## Results
- [x] Per-strategy: trades, win rate, gross P&L, holding period, gate blocks
- [x] No combined equity curve across strategies
- [x] `biases` attached to every result

## API
- [x] `POST /backtest/run`

## Tests
- [x] A strategy sees no bar after the as-of date
- [x] Truncation happens for every interval and lookback
- [x] Fills use the next session's open, not the signal bar's close
- [x] The runner skips non-trading days
- [x] Positions fold identically to the live ledger
- [x] No aggregate-across-strategies field exists
- [x] Every result carries its bias report
- [x] Legacy tables are never read

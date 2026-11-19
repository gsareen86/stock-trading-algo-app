# Tasks: backtest-plans

## Spec
- [x] `proposal.md`, `tasks.md`
- [x] Deltas: backtesting (ADDED + MODIFIED), platform-api (MODIFIED)
- [ ] Merge into `openspec/specs/backtesting/` and archive after the first real multi-year run

## Replay — `app/backtest/`
- [x] `ReplayPriceSource`: preloaded, IST-session cut, live minimum window, weekly resample
- [x] `AsOfFundamentalsSource` and `filed_by` (45 / 60 days)
- [x] `exits.py`: one rule per registered strategy, each stating what it does not model
- [x] Buy-stop entry, chase limit, invalidation, expiry; `next_open` mode kept
- [x] Stops every session, gap handling, entry-session stop
- [x] Rule, thesis-broken and hold-limit exits at the next open
- [x] One in-memory `Ledger` per strategy, disposed after each symbol
- [x] Trade records: net return, R-multiple, benchmark return, excess
- [x] Per-strategy distribution and conviction bands; no cross-strategy figure
- [x] Sessions from the market index for calendar-uncovered years, reported
- [x] Sector-less runs reported as a limitation
- [x] `workers > 1` by symbol; same results as one worker; Windows `spawn` safe
- [x] `cli.py`: universe, workers, options, JSON report, trades CSV, printed summary

## API
- [x] New options on `POST /backtest/run`; interactive bounds (100 symbols, 3 years)
- [x] Sectors from the universe and bundled list
- [x] Replay off the event loop

## Tests
- [x] `tests/test_backtest_replay.py` — entries, exits, costs, slippage, excess, ledgers,
      conviction bands, lookahead, sectors, filing deadlines, exit rules, calendar fallback,
      parallel equivalence, API options and bounds
- [x] Existing `tests/test_backtest.py` passes unchanged

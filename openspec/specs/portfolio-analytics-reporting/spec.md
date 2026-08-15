# Portfolio Analytics & Reporting

Status: baseline — not yet exercised through a change under `openspec/changes/`.

Performance metrics computed from raw trade/position cash-flow rows — Sharpe, Sortino,
drawdown, win rate, per-strategy P&L.

## Requirements

### Requirement: Metrics are computed from cash-flow rows, correctly under partials and SHORTs
The system MUST compute Sharpe ratio, Sortino ratio, max drawdown, win rate, profit
factor, and per-strategy P&L directly from the `trades`/`positions` tables' cash-flow
entries, with logic that correctly handles partial (T1) closes and SHORT positions rather
than assuming every trade is a single full-quantity LONG round-trip.

#### Scenario: Position closed in two legs (T1 partial + trailing-stop remainder)
- GIVEN a LONG position that exited via a 50% T1 partial followed later by a trailing-stop
  close on the remaining 50%
- WHEN win-rate and P&L metrics are computed
- THEN both legs' realized P&L are summed into that position's total result, not counted
  as two independent trades or only the final leg counted

### Requirement: Reporting is per-book, not blended by default
The system MUST be able to report metrics separately per book (intraday vs. positional),
consistent with each book having its own independent capital pool and ledger (see
`openspec/project.md` architecture map) — a blended, all-books number is not the primary
reporting shape.

#### Scenario: Comparing books
- GIVEN both the intraday and positional books have closed trades
- WHEN a user wants to compare their Sharpe ratios
- THEN they query each book's ledger separately — there is no single pre-blended
  "portfolio-wide" metric combining ledgers that use different capital pools

## Known gaps / gotchas

- Correctness under partial closes and SHORT accounting was reworked at least once
  (per in-code comments) — this is exactly the kind of arithmetic that's easy to silently
  break in a future change; worth a regression check (manual, since no test suite exists)
  whenever this module is touched.
- No automated tests back this module's calculations — see `openspec/project.md`'s
  testing section.

## Source modules

`analytics/metrics.py`.

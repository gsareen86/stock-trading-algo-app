# Positional / Swing Trading

Status: baseline — not yet exercised through a change under `openspec/changes/`.

The EOD (daily-candle) book. Off by default (`positional_enabled`, a `bot_control`
column, toggled from the dashboard Control Panel). Strategy signals and pillar scoring
feed `specs/conviction-engine-scoring-routing`; this spec covers the book's own
mechanics — universe, sizing, exits, scheduling.

## Requirements

### Requirement: Universe must pass quality and institutional-interest filters
The system MUST restrict scanning to tickers where `lt_universe.in_universe = 1`,
`lt_quality.total_score >= 60`, `lt_universe.fii_pct >= 5%`, and the quality score is no
more than 30 days old, falling back to a hardcoded Tier-1 list of 24 NIFTY 50 large-caps
when the database is cold (no scored universe yet).

#### Scenario: Cold database
- GIVEN `lt_universe`/`lt_quality` have no rows yet (fresh install)
- WHEN the EOD scan runs
- THEN it scans the hardcoded 24-ticker Tier-1 fallback list instead of returning nothing

### Requirement: Entries are risk-sized, not equal-weight
The system MUST size positions by `qty = (POSITIONAL_RISK_PCT_POOL × pool) /
(entry − stop)` when `POSITIONAL_USE_RISK_SIZING` is true (current default), capped at
20% of the positional pool per position and a 30% sector cap — replacing an earlier
equal-weight approach that is still available via the flag.

#### Scenario: Risk sizing disabled
- GIVEN `POSITIONAL_USE_RISK_SIZING = False`
- WHEN a new position is sized
- THEN the book reverts to equal-weight sizing rather than risk-to-stop sizing

### Requirement: Exit stack — hard stop, partial de-risk, trail, time stop, event exits
The system MUST manage open positions with, in priority order: a structural hard stop
(capped at 8%); a partial de-risk at +2R (sell half, move stop to breakeven,
`POSITIONAL_PARTIAL_AT_R`); a 21-EMA double-close trail on the remainder; a time stop that
scales with the entering strategy's expected hold (`POSITIONAL_TIME_STOP_USE_STRATEGY`);
and event-driven exits (critical negative news-impact on a held name, or a management
score dropping below `POSITIONAL_MANAGEMENT_REVIEW_SCORE`).

#### Scenario: Management score deterioration
- GIVEN a held position's management score drops to/below `POSITIONAL_MANAGEMENT_REVIEW_SCORE` (35)
- WHEN the daily research refresh runs
- THEN a review alert is raised; the position is only force-exited if
  `POSITIONAL_MANAGEMENT_AUTO_EXIT` is also true (default `False` — advisory-only unless
  explicitly enabled)

### Requirement: Deterministic event guard blocks entries near known results dates
The system MUST block new entries within `POSITIONAL_EVENT_GUARD_DAYS` (3) trading days
of a known results date sourced from the NSE calendar
(`specs/market-data-ingestion`) — not from LLM-inferred dates — except for
fun-tech-momentum-style entries which are designed to trade *after* results.

#### Scenario: NSE calendar stale or empty
- GIVEN the NSE events calendar has not refreshed successfully recently
- WHEN a new entry is evaluated
- THEN the event guard does not block it (fail-open — see `specs/market-data-ingestion`)

### Requirement: Scheduled cadence
The system MUST run a pre-market universe/research scan around 08:30 IST, the EOD entry
scan at `POSITIONAL_SCAN_TIME` (16:00 IST, after close), an exit check at
`POSITIONAL_EXIT_TIME` (15:20 IST), and a Telegram summary at `POSITIONAL_ALERT_TIME`
(16:30 IST), as time-of-day checks inside a polling daemon thread — not a cron/scheduler
library. See `specs/scheduling-and-orchestration` for the general mechanism (per-day
tracking variables, late-boot behavior); this requirement is about the positional book's
specific target times.

#### Scenario: Exit check runs before the entry scan on the same day
- GIVEN the clock reaches 15:20 IST (exit-check time) before 16:00 IST (entry-scan time)
  on the same trading day
- WHEN the positional loop's daily checks run in order
- THEN exit management for existing positions happens first, using that day's prices,
  before any new entries from the EOD scan are considered later the same day

## Known gaps / gotchas

- Own position ledger (`pos_positions`/`pos_trades`) and own sizing/exit code
  (`positional/risk.py`) — not shared with intraday or long-term (see
  `openspec/project.md` architecture map).
- Broker execution is a stub for this book specifically (`positional/broker.py`'s
  `SharekhanBroker`/`ZerodhaBroker`) — see `specs/broker-execution-and-costs`.
- The hygiene gate (`specs/market-hygiene-and-surveillance`) applies here, unlike
  intraday.
- Auto-arm-on-boot logic (whether research/scans re-run automatically after a server
  restart) has a documented history of bugs — see `specs/scheduling-and-orchestration`.

## Source modules

`positional/scanner.py`, `positional/strategies/*`, `positional/screener.py`,
`positional/universe.py`, `positional/universe_sync.py`, `positional/risk.py`,
`positional/runner.py`, `positional/market_regime.py`, `positional/ipo.py`,
`positional/sectors.py`, `positional/alerts.py`.

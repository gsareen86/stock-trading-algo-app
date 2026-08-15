# Tasks: market-data-foundation

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: market-data, market-calendar, platform-api

## Domain
- [x] `app/domain/instrument.py` — `Instrument`, NSE↔provider symbol mapping
- [x] `app/domain/prices.py` — `PriceSeries` with boundary validation and provenance

## Data sources
- [x] `app/data/protocols.py` — `PriceSource`, `UniverseSource`, `MarketCalendar`
- [x] `app/data/yfinance_source.py` — ported from `data/fetcher.py`, daily/weekly only
- [x] `app/data/cache.py` — `CachingPriceSource` decorator; stale-on-failure
- [x] `app/data/universe.py` — NSE constituents, fallback + blocklist provenance
- [x] `app/data/fake.py` — `FakePriceSource` for downstream increments

## Calendar
- [x] `app/data/resources/nse_holidays.json` — holidays by year
- [x] `app/data/calendar.py` — `NseCalendar`, `CalendarNotCovered`, coverage, session hours

## Resources
- [x] `app/data/resources/nse_fallback_universe.json` — bundled constituent list
- [x] `app/data/resources/blocked_tickers.json` — known-bad symbols

## API
- [x] `/health` reports calendar coverage; stale calendar degrades

## Tests (all offline)
- [x] `PriceSeries` validation: capitalisation, MultiIndex, nulls, sort, missing column
- [x] Interval restricted to daily/weekly
- [x] Cache: fresh hit, expiry refetch, stale-on-failure, standalone source
- [x] Source failure returns empty, never raises
- [x] Symbol mapping incl. already-suffixed
- [x] Universe: live vs fallback provenance, blocklist applied to both
- [x] Calendar: weekday/weekend/holiday, uncovered year raises, coverage query
- [x] Session hours incl. UTC input and holiday-during-hours
- [x] Most-recent-trading-day incl. holiday weekend
- [x] `FakePriceSource` determinism
- [x] No test performs network I/O

## Verify & ship
- [x] `pytest`, `ruff`; `/health` shows calendar coverage
- [x] Archive deltas into `openspec/specs/`, move change to `openspec/archive/`
- [x] Commit, push

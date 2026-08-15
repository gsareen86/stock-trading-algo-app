# Market Data Ingestion

Status: baseline — not yet exercised through a change under `openspec/changes/`.

Wraps yfinance as the primary OHLCV source with a parquet disk cache, and provides the
two universe sources (which tickers exist to trade) and the NSE calendar (holidays +
corporate events) that gate almost every downstream job.

## Requirements

### Requirement: Candle fetches are cached to disk with an interval-dependent TTL
The system MUST cache fetched OHLCV candles as parquet files keyed by ticker + interval,
and MUST fetch tickers in parallel via a thread pool (8 workers) rather than serially.

#### Scenario: Cache hit within TTL
- GIVEN a cached parquet file for a ticker/interval younger than its TTL
- WHEN candles are requested
- THEN the cache is served without a network call

#### Scenario: Stale or missing cache
- GIVEN no cache file exists, or it is older than its TTL
- WHEN candles are requested
- THEN the system refetches from yfinance and overwrites the cache

### Requirement: Two independent universe sources, selected by `UNIVERSE_SOURCE`
The system MUST support both a legacy NIFTY 500 list (NSE CSV download with a hardcoded
~200-symbol fallback) and an expanded all-NSE-equity master (market-cap floor +
IPO-tracking), switched by the `UNIVERSE_SOURCE` env-backed config value
(`"nse_all"` default, or `"nifty500"`).

#### Scenario: NSE download unavailable
- GIVEN the NSE CSV endpoint is unreachable
- WHEN the NIFTY 500 universe is built
- THEN the system falls back to its hardcoded ~200-symbol list rather than failing

### Requirement: Market-hours and holiday gating
The system MUST gate downstream trading jobs on `market_is_open()`, which checks a
**hardcoded set of dates for the current year** maintained in `data/fetcher.py` — this
set MUST be manually updated annually; there is no dynamic holiday-calendar fetch for
market status (the NSE corporate-events calendar, below, is separate and does auto-refresh).

#### Scenario: Year boundary without an update
- GIVEN the hardcoded holiday set has not been updated for a new calendar year
- WHEN `market_is_open()` is evaluated on a real NSE holiday in that new year
- THEN the system will incorrectly treat that day as a trading day (a known, named
  maintenance burden, not a defect to silently work around)

### Requirement: NSE corporate-events calendar is fail-open
The system MUST refresh the board-meeting/results calendar (`data/nse_calendar.py`) on a
throttle (`EVENT_CALENDAR_REFRESH_HOURS`, 12h) and MUST NOT block any entry decision when
the calendar is empty or stale — only a *known* upcoming event blocks.

#### Scenario: NSE calendar source unreachable
- GIVEN the NSE calendar scrape fails
- WHEN a positional entry is evaluated against the event guard
- THEN the entry is not blocked by the event guard (fail-open), though other gates still
  apply

## Known gaps / gotchas

- The market-holiday set and the NSE corporate-events calendar are two separate
  mechanisms with different refresh behavior (static/manual vs. throttled/automatic) —
  easy to conflate.
- The NIFTY 500 CSV fallback list is a hardcoded, point-in-time snapshot and will drift
  from the real index composition over time.

## Source modules

`data/fetcher.py`, `data/universe.py`, `data/nse_calendar.py`.

# market-data

## ADDED Requirements

### Requirement: Price data crosses the seam validated
Every `PriceSeries` handed to application code MUST have a lowercase `open`, `high`, `low`,
`close`, `volume` schema, a timezone-aware UTC index sorted ascending, and no incomplete rows.

#### Scenario: Provider capitalisation normalised
- GIVEN a provider returning columns `Open`, `High`, `Low`, `Close`, `Volume`
- WHEN a `PriceSeries` is constructed
- THEN its frame's columns are lowercase

#### Scenario: MultiIndex columns flattened
- GIVEN yfinance returns MultiIndex columns for a single symbol
- WHEN a `PriceSeries` is constructed
- THEN the frame has a flat column index

#### Scenario: Rows with missing values dropped
- GIVEN a frame containing a row with a null close
- WHEN a `PriceSeries` is constructed
- THEN that row is absent from the result

#### Scenario: Unsorted index sorted
- GIVEN a frame whose rows are not in ascending time order
- WHEN a `PriceSeries` is constructed
- THEN the frame index is ascending

#### Scenario: Missing required column rejected
- GIVEN a frame with no `volume` column
- WHEN a `PriceSeries` is constructed
- THEN construction raises an error naming the missing column

### Requirement: Series carry their provenance
A `PriceSeries` MUST record the instrument, interval, fetch time and the source that produced
it.

#### Scenario: Live fetch labelled
- GIVEN a series fetched from the provider
- WHEN it is returned
- THEN its source names the provider

#### Scenario: Cached read labelled
- GIVEN a series served from the on-disk cache
- WHEN it is returned
- THEN its source identifies it as cached
- AND a caller can distinguish it from a live fetch

### Requirement: Only daily and weekly intervals exist
The system MUST support the `1d` and `1wk` intervals only.

#### Scenario: Daily and weekly accepted
- GIVEN a request for the `1d` or `1wk` interval
- WHEN prices are fetched
- THEN the request is served

#### Scenario: Intraday interval rejected
- GIVEN a request for a `15m` interval
- WHEN prices are fetched
- THEN the request is rejected rather than served

### Requirement: Caching is a separate layer over any price source
The system MUST provide caching as a wrapper implementing the same `PriceSource` protocol, so
a source can be used with or without it.

#### Scenario: Fresh entry served without a provider call
- GIVEN a cached series within its time-to-live
- WHEN the same series is requested
- THEN it is returned from cache
- AND the wrapped source is not called

#### Scenario: Expired entry refetched
- GIVEN a cached series older than its time-to-live
- WHEN the series is requested
- THEN the wrapped source is called
- AND the cache is updated

#### Scenario: Uncached source works standalone
- GIVEN a price source used without the caching wrapper
- WHEN a series is requested
- THEN it is fetched and returned with no filesystem access

### Requirement: A stale cache entry beats no data when the provider fails
When the wrapped source fails and an expired cache entry exists, the system MUST return the
stale entry rather than nothing.

#### Scenario: Provider down, stale entry present
- GIVEN an expired cache entry for a series
- AND the wrapped source raises on fetch
- WHEN the series is requested
- THEN the stale entry is returned
- AND it is labelled as cached

#### Scenario: Provider down, nothing cached
- GIVEN no cache entry for a series
- AND the wrapped source raises on fetch
- WHEN the series is requested
- THEN an empty result is returned rather than an exception propagating

### Requirement: A failed price fetch never raises
`PriceSource.history` MUST return an empty result on provider failure rather than raising.

#### Scenario: Provider errors
- GIVEN the provider raises on fetch
- WHEN history is requested
- THEN an empty series is returned
- AND no exception escapes the source

#### Scenario: Unknown symbol
- GIVEN a symbol the provider has no data for
- WHEN history is requested
- THEN an empty series is returned

### Requirement: Instrument symbols are mapped to provider form at the boundary
The system MUST translate NSE symbols to the provider's ticker form inside the source, and
MUST NOT require callers to know that form.

#### Scenario: NSE symbol suffixed for the provider
- GIVEN the instrument `RELIANCE`
- WHEN history is fetched from the yfinance source
- THEN the provider is queried for `RELIANCE.NS`

#### Scenario: Already-suffixed symbol not double-suffixed
- GIVEN the symbol `RELIANCE.NS`
- WHEN history is fetched
- THEN the provider is queried for `RELIANCE.NS`

### Requirement: Universe snapshots record how they were obtained
A universe snapshot MUST record whether its constituents came from the live index source or
the bundled fallback.

#### Scenario: Live constituent list
- GIVEN the index source responds successfully
- WHEN the universe is requested
- THEN the snapshot is labelled as live

#### Scenario: Source unavailable
- GIVEN the index source fails
- WHEN the universe is requested
- THEN the bundled fallback constituents are returned
- AND the snapshot is labelled as a fallback

### Requirement: Known-bad tickers are excluded from the universe
The system MUST exclude blocklisted symbols from every universe snapshot, whether live or
fallback.

#### Scenario: Blocklisted symbol removed from a live list
- GIVEN the index source returns a blocklisted symbol
- WHEN the universe is requested
- THEN that symbol is absent from the snapshot

#### Scenario: Blocklist is data, not code
- GIVEN the blocklist file
- WHEN a symbol is added to it
- THEN no code change is needed for it to take effect

### Requirement: A deterministic price source exists for testing
The system MUST provide a fake `PriceSource` producing deterministic series, so downstream
changes can be tested without a provider.

#### Scenario: Same request yields the same series
- GIVEN a fake source seeded for an instrument
- WHEN the same history is requested twice
- THEN both results are identical

#### Scenario: No network or filesystem used
- GIVEN the fake source
- WHEN history is requested
- THEN no network request and no file read occurs

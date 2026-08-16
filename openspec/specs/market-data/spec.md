# market-data

Price history and the investable universe: validated at the seam, cached in a layer, and reproducible offline.

Introduced by `market-data-foundation` (see `openspec/archive/`).

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
MUST NOT require callers to know that form. Index tickers, which the provider addresses by a
caret-prefixed code with no suffix, MUST be passed through unchanged rather than treated as an
NSE equity code needing `.NS` appended.

#### Scenario: NSE symbol suffixed for the provider
- GIVEN the instrument `RELIANCE`
- WHEN history is fetched from the yfinance source
- THEN the provider is queried for `RELIANCE.NS`

#### Scenario: Already-suffixed symbol not double-suffixed
- GIVEN the symbol `RELIANCE.NS`
- WHEN history is fetched
- THEN the provider is queried for `RELIANCE.NS`

#### Scenario: Index ticker is not suffixed
- GIVEN the benchmark or a sector index, e.g. `^NSEI` or `^CNXIT`
- WHEN history is fetched from the yfinance source
- THEN the provider is queried for that ticker unchanged, not `^NSEI.NS`

<!--
  Found live, not designed for: every strategy test before real-data testing used a fake
  price source keyed by the raw symbol string, so nothing exercised this translation. Against
  the real provider, the untranslated benchmark instrument resolved to `NIFTY50.NS`, which
  does not exist — every relative-strength criterion built on it failed silently, because
  "unavailable" is itself a valid, non-exceptional outcome for that criterion. Fixed at
  `Instrument`/`to_provider_ticker`, the one seam every symbol crosses, rather than as a
  special case in each caller. See `app/domain/instrument.py`.
-->

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

### Requirement: Quarterly fundamentals are available through a narrow seam
The system MUST expose quarterly EPS and revenue series for an instrument, most recent first,
and MUST NOT require any other fundamental field.

#### Scenario: Series returned most recent first
- GIVEN a fundamentals source with four quarters of data
- WHEN quarterly fundamentals are requested
- THEN the EPS and revenue series are returned newest first

#### Scenario: Each series carries a source reference
- GIVEN quarterly fundamentals for an instrument
- WHEN they are read
- THEN a source reference identifying the provider is present

#### Scenario: Unavailable fundamentals return nothing rather than raising
- GIVEN a provider that fails
- WHEN quarterly fundamentals are requested
- THEN the result is empty
- AND no exception escapes the source

#### Scenario: Unknown instrument
- GIVEN an instrument the provider has no fundamentals for
- WHEN they are requested
- THEN the result is empty

### Requirement: A deterministic fundamentals source exists for testing
The system MUST provide a fundamentals source returning supplied data without network access.

#### Scenario: Supplied quarters returned unchanged
- GIVEN a static source seeded with quarters for a symbol
- WHEN they are requested
- THEN exactly those quarters are returned

#### Scenario: Unseeded symbol returns empty
- GIVEN a static source with no data for a symbol
- WHEN fundamentals are requested
- THEN the result is empty

### Requirement: Sector membership maps to a sector index
The system MUST map an instrument's industry description to an NSE sector index, from a data
file rather than code.

#### Scenario: Known industry maps to its index
- GIVEN an instrument whose industry is a financial-services description
- WHEN its sector index is resolved
- THEN the banking sector index is returned

#### Scenario: Unknown industry resolves to nothing
- GIVEN an instrument with an unrecognised industry
- WHEN its sector index is resolved
- THEN no index is returned rather than a wrong one

#### Scenario: Mapping is data
- GIVEN the sector mapping file
- WHEN an industry is added to it
- THEN no code change is needed for it to take effect

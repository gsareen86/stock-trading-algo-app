# market-data

## ADDED Requirements

### Requirement: Live quotes are available through their own seam
The system MUST expose a quote source returning the current price and the official previous
close for an instrument or an index, separately from the historical price seam.

#### Scenario: A quote carries its provider and its time
- GIVEN a quote for an instrument
- WHEN it is read
- THEN it carries the price, the time it was observed, and the provider that supplied it

#### Scenario: An index quote is available by index symbol
- GIVEN an index symbol
- WHEN a quote is requested
- THEN the index level and its previous close are returned

#### Scenario: A failed quote fetch returns nothing rather than raising
- GIVEN a provider that fails or refuses the request
- WHEN a quote is requested
- THEN the result is empty
- AND no exception escapes the source

#### Scenario: A quote outside market hours reports the last traded price
- GIVEN a request made when the market is closed
- WHEN a quote is requested
- THEN the last traded price is returned, marked as of its own observation time

### Requirement: A live quote never enters a historical series
A quote MUST NOT be appended to, or substituted into, any price series a strategy reads.

#### Scenario: Strategies see only settled bars
- GIVEN a live quote available for an instrument
- WHEN a strategy evaluates that instrument
- THEN the series it reads contains only bars from the historical source

#### Scenario: Verdicts do not move with the quote
- GIVEN a verdict produced for an instrument
- WHEN the live quote changes and the verdict is recomputed against the same bars
- THEN the verdict is unchanged

### Requirement: An official-source client identifies itself and limits its own rate
A source reading the exchange's own endpoints MUST send browser-equivalent headers, maintain
the session cookies those endpoints require, and bound its own request rate.

#### Scenario: Session cookies are established before a data request
- GIVEN a fresh client
- WHEN the first data request is made
- THEN a session has been established first

#### Scenario: A refusal degrades rather than raises
- GIVEN an endpoint that refuses the client
- WHEN a request is made
- THEN the result is empty and the refusal is logged
- AND no exception escapes the source

#### Scenario: Request rate is bounded
- GIVEN a burst of quote requests
- WHEN they are issued
- THEN they are spaced so the configured rate is not exceeded

#### Scenario: A blocked provider falls back to cached data
- GIVEN an index level available in cache and a blocked live provider
- WHEN the level is requested
- THEN the cached value is returned, labelled as cached

### Requirement: Company financials are available through a wide seam, separate from the strategy seam
The system MUST expose reported financials, derived ratios and shareholding for an instrument
through a seam distinct from the quarterly EPS and revenue seam strategies read.

#### Scenario: The narrow seam is unchanged
- GIVEN the quarterly fundamentals seam
- WHEN the wide seam is added
- THEN quarterly EPS and revenue are still served with no additional required field

#### Scenario: Reported statements are returned most recent first
- GIVEN financials for an instrument
- WHEN they are read
- THEN income, balance sheet and cashflow periods are ordered newest first

#### Scenario: Every figure carries its period and its source
- GIVEN any financial figure
- WHEN it is read
- THEN the period it belongs to and the provider that supplied it are present

#### Scenario: A derived ratio names its inputs
- GIVEN a ratio the platform computed rather than received
- WHEN it is read
- THEN the figures it was computed from are identifiable

#### Scenario: Missing financials are empty, never zero
- GIVEN an instrument the provider has no financials for
- WHEN they are requested
- THEN the result is empty
- AND no field defaults to zero

#### Scenario: A missing API key disables one capability only
- GIVEN no financials API key is configured
- WHEN financials are requested
- THEN the result is empty and the reason names the missing configuration
- AND price data, screening and every strategy continue to work

### Requirement: Shareholding is reported with its pattern date
The system MUST expose promoter, FII, DII and public holding percentages for an instrument,
each with the quarter the pattern was filed for, and promoter pledge where it is reported.

#### Scenario: Holdings carry their quarter
- GIVEN a shareholding pattern
- WHEN it is read
- THEN the quarter it was filed for is present

#### Scenario: Pledge is distinguishable from absent
- GIVEN a company reporting no pledged promoter holding
- WHEN shareholding is read
- THEN zero pledge is distinguishable from pledge not being reported

#### Scenario: Stale patterns are labelled, not hidden
- GIVEN the most recent available pattern is two quarters old
- WHEN it is read
- THEN it is returned with its own date rather than withheld

### Requirement: Financial data is cached at a period-appropriate lifetime
The system MUST cache financials and shareholding for a lifetime measured in days, and MUST
serve cached data when the provider is unavailable or rate-limits.

#### Scenario: A repeat request inside the lifetime does not call the provider
- GIVEN financials fetched within the cache lifetime
- WHEN they are requested again
- THEN the cached copy is returned and no provider call is made

#### Scenario: A rate-limited provider serves cache
- GIVEN a provider returning a rate-limit response
- WHEN financials are requested and a cached copy exists
- THEN the cached copy is returned, labelled as cached

#### Scenario: A rate-limited provider with no cache returns empty
- GIVEN a rate-limited provider and no cached copy
- WHEN financials are requested
- THEN the result is empty rather than an exception

## MODIFIED Requirements

### Requirement: Sector membership maps to a sector index
The system MUST map an instrument's industry description to an NSE sector index, from a data
file rather than code, and every sector index it names MUST be verified to return usable
history before it is added.

#### Scenario: Known industry maps to its index
- GIVEN an instrument whose industry is a financial-services description
- WHEN its sector index is resolved
- THEN the banking sector index is returned

#### Scenario: Unknown industry resolves to nothing
- GIVEN an instrument with an unrecognised industry
- WHEN its sector index is resolved
- THEN no index is returned rather than a wrong one

#### Scenario: A sector index without usable history is not offered
- GIVEN a candidate sector index whose provider returns insufficient history
- WHEN the sector table is loaded
- THEN that index is absent from the table rather than present and unusable

#### Scenario: The benchmark set includes the broad-market index
- GIVEN the platform's index set
- WHEN it is read
- THEN both the Nifty 50 and the Nifty 500 are available as benchmarks

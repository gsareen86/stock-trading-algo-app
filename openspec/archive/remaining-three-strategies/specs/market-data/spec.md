# market-data

## ADDED Requirements

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

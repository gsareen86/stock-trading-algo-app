# platform-api

## ADDED Requirements

### Requirement: The investable universe is inspectable
`GET /universe` MUST return the current universe snapshot, how it was obtained, and any
symbols excluded from it.

#### Scenario: Snapshot reports its origin
- GIVEN a universe snapshot
- WHEN it is requested
- THEN whether it came from the live source or the bundled fallback is reported

#### Scenario: Blocklisted symbols are visible
- GIVEN symbols removed by the blocklist
- WHEN the universe is requested
- THEN those symbols are reported separately from the constituents

### Requirement: A screen can be run on demand
`POST /screen` MUST apply eligibility filters to the universe and return the eligible
instruments together with why the others were excluded.

#### Scenario: Screen reports eligible and excluded
- GIVEN a universe
- WHEN a screen is requested
- THEN the eligible instruments and a per-filter exclusion count are returned

#### Scenario: Exclusion detail can be omitted without losing the counts
- GIVEN a screen requested without exclusion detail
- WHEN the response is read
- THEN individual exclusions are absent
- AND the per-filter counts remain

#### Scenario: Surveillance freshness is reported
- GIVEN a screen result
- WHEN it is read
- THEN the surveillance list's date and staleness are present

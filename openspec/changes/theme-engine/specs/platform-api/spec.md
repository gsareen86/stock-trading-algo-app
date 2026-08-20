# platform-api

## ADDED Requirements

### Requirement: Themes and their runs are readable
The API MUST expose starting a theme run, listing past runs, and reading the themes a run
produced with their supporting evidence.

#### Scenario: A run can be requested
- GIVEN an authenticated caller
- WHEN a theme run is requested
- THEN a run identifier is returned

#### Scenario: Themes are returned with their counts and sources
- GIVEN a completed run
- WHEN its themes are requested
- THEN each carries its company count, period count and the source kinds behind it

#### Scenario: Withdrawn themes are excluded by default
- GIVEN a run containing standing and withdrawn themes
- WHEN themes are requested with no filter
- THEN only standing themes are returned

#### Scenario: A run that produced no reading is distinguishable
- GIVEN a run in which every source was unavailable
- WHEN it is read
- THEN it reports that no reading was produced, not that no themes exist

#### Scenario: A second concurrent run is refused
- GIVEN a theme run in progress
- WHEN another is requested
- THEN it is refused with the running run identified

### Requirement: A theme's chain and candidates are readable, and links are rejectable
The API MUST serve a theme's tiers with each link's reasoning, the candidates each tier
resolved to, and MUST accept a rejection of a single link.

#### Scenario: Tiers are served with reasoning and attribution
- GIVEN a theme with a chain
- WHEN it is requested
- THEN each tier carries its reasoning and the model that proposed it

#### Scenario: Candidates carry their exposure grade
- GIVEN a resolved tier
- WHEN its candidates are read
- THEN each carries a named exposure grade and what supports it

#### Scenario: A tier with no listed exposure is reported as such
- GIVEN a tier that resolved to nothing
- WHEN it is read
- THEN it is marked as having no Indian listed exposure

#### Scenario: Rejecting a link persists
- GIVEN a rejected link
- WHEN the theme is read again after a later run
- THEN the link remains rejected

#### Scenario: Rejection never writes a trade
- GIVEN any link being rejected
- WHEN the request completes
- THEN no trade is recorded and no position changes

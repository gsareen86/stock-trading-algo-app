# themes

## ADDED Requirements

### Requirement: A tier that name matching cannot resolve is searched
The system MUST attempt a search for Indian listed participants when a tier resolves to no
candidate, and MUST record whether that search ran.

#### Scenario: An unresolved tier triggers a search
- GIVEN a tier no company matched on name or industry
- WHEN the tier is resolved
- THEN a search for Indian listed participants is attempted

#### Scenario: A tier that already resolved is not searched
- GIVEN a tier that matched companies on name or industry
- WHEN it is resolved
- THEN no search is performed

#### Scenario: An unavailable search is recorded, never guessed at
- GIVEN a search provider that cannot be reached
- WHEN a tier is searched
- THEN the tier reports that it was not searched
- AND no candidate is produced

#### Scenario: A searched tier that still finds nothing says which was true
- GIVEN a tier that was searched and produced no listed participant
- WHEN it is read
- THEN it is distinguishable from a tier that was never searched

### Requirement: A proposed company is inert until the universe confirms it
A company name proposed by search MUST be resolved against the platform's universe before it
becomes a candidate, and an unresolved proposal MUST NOT be offered.

#### Scenario: A proposal matching the universe becomes a candidate
- GIVEN a proposed company name matching an instrument in the universe
- WHEN proposals are validated
- THEN it becomes a candidate carrying that instrument's symbol

#### Scenario: A proposal matching nothing is recorded but never offered
- GIVEN a proposed company name matching no instrument in the universe
- WHEN proposals are validated
- THEN it is recorded as proposed but not found
- AND it does not appear among candidates

#### Scenario: An ambiguous proposal is not resolved by guessing
- GIVEN a proposed name matching more than one instrument
- WHEN proposals are validated
- THEN no candidate is produced from it
- AND the ambiguity is recorded

#### Scenario: A company listed elsewhere is never a candidate
- GIVEN a proposed company listed outside India
- WHEN proposals are validated
- THEN it does not appear among candidates

### Requirement: Every search-derived proposal carries a citation
A proposal MUST carry at least one followable source, and a proposal without one MUST be
discarded rather than shown.

#### Scenario: A proposal carries the source it came from
- GIVEN a validated proposal
- WHEN it is read
- THEN at least one source URL is present

#### Scenario: An uncited proposal is discarded
- GIVEN a proposal with no source
- WHEN proposals are validated
- THEN it is discarded and does not become a candidate

#### Scenario: The citation is shown wherever the candidate is
- GIVEN a search-derived candidate on any surface
- WHEN it is displayed
- THEN its citation is reachable from where it is shown

### Requirement: A search-derived candidate is graded as such
A candidate produced by search MUST carry an exposure basis naming search as its origin, and
MUST NOT be graded above the weakest grade on the strength of the search alone.

#### Scenario: The grade records the origin
- GIVEN a search-derived candidate
- WHEN its exposure is read
- THEN the basis names search and the source that proposed it

#### Scenario: Search alone does not establish exposure
- GIVEN a candidate proposed only by search
- WHEN its exposure is graded
- THEN it is graded as unestablished

#### Scenario: Corroboration can raise the grade
- GIVEN a search-derived candidate whose own commentary also discusses the theme
- WHEN its exposure is graded
- THEN it may be graded as claimed, citing that commentary rather than the search

### Requirement: Research may only widen the candidate set
Search MUST NOT remove a candidate, exclude an instrument from evaluation, alter a stance or a
conviction, or change any ordering.

#### Scenario: Verdicts are unchanged by research
- GIVEN the same instruments and the same price data
- WHEN verdicts are produced with research active and again with it disabled
- THEN the verdicts are identical

#### Scenario: Research cannot remove an existing candidate
- GIVEN a tier with candidates found by name matching
- WHEN research runs
- THEN every existing candidate remains

#### Scenario: No research output becomes evidence
- GIVEN a search-derived candidate
- WHEN a verdict is produced for it
- THEN no evidence row cites the search or its sources

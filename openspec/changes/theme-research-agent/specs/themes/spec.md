# themes

## ADDED Requirements

### Requirement: Every tier is decomposed before it is resolved
The system MUST attempt to decompose each chain tier into finer sub-categories, and MUST resolve
those sub-categories by the ordinary path. Decomposition MUST run whether or not the coarse tier
resolved to anything.

#### Scenario: A tier that already resolved is still decomposed
- GIVEN a tier that matched companies on their business descriptions
- WHEN the chain is resolved
- THEN the tier is decomposed anyway
- AND its existing candidates all remain

#### Scenario: Decomposition sharpens which company matches
- GIVEN a tier for semiconductor fabrication that matches several companies weakly
- WHEN it is decomposed into assembly and test, design services and lithography
- THEN a company describing outsourced semiconductor assembly matches the assembly sub-category
  more strongly than it matched the coarse tier

#### Scenario: A sub-category with no Indian expression says so precisely
- GIVEN a sub-category for EUV lithography
- WHEN it is resolved
- THEN it reports that no Indian listed company matched
- AND that statement is recorded against the sub-category rather than the coarse tier

#### Scenario: Decomposition proposes categories, never companies
- GIVEN any decomposed tier
- WHEN its sub-categories are read
- THEN each names a category of supplier
- AND no sub-category is an instrument symbol

#### Scenario: A tier that cannot be decomposed resolves as before
- GIVEN a model that cannot be reached
- WHEN a tier is decomposed
- THEN the tier resolves by its coarse description
- AND the tier records that decomposition did not run

### Requirement: A sub-category that description matching cannot resolve is searched
The system MUST attempt a search for Indian listed participants when a sub-category resolves to
no candidate, and MUST record whether that search ran.

#### Scenario: An unresolved sub-category triggers a search
- GIVEN a sub-category no company matched on its business description
- WHEN it is resolved
- THEN a search for Indian listed participants is attempted

#### Scenario: A resolved sub-category is not searched
- GIVEN a sub-category that matched companies on their business descriptions
- WHEN it is resolved
- THEN no search is performed

#### Scenario: An unavailable search is recorded, never guessed at
- GIVEN a search provider that cannot be reached
- WHEN a sub-category is searched
- THEN the sub-category reports that it was not searched
- AND no candidate is produced

#### Scenario: An exhausted allowance is not a quiet absence
- GIVEN a search allowance that has been used up
- WHEN a sub-category is searched
- THEN it reports that the allowance was exhausted
- AND that is distinguishable from a provider that could not be reached

#### Scenario: A searched sub-category that still finds nothing says which was true
- GIVEN a sub-category that was searched and produced no listed participant
- WHEN it is read
- THEN it is distinguishable from one that was never searched

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
Decomposition and search MUST NOT remove a candidate, exclude an instrument from evaluation,
alter a stance or a conviction, or change any ordering.

#### Scenario: Verdicts are unchanged by research
- GIVEN the same instruments and the same price data
- WHEN verdicts are produced with research active and again with it disabled
- THEN the verdicts are identical

#### Scenario: Research cannot remove an existing candidate
- GIVEN a tier with candidates found by description matching
- WHEN research runs
- THEN every existing candidate remains

#### Scenario: No research output becomes evidence
- GIVEN a search-derived candidate
- WHEN a verdict is produced for it
- THEN no evidence row cites the search or its sources

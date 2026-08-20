# themes

What is changing in the market, and who is positioned to be paid by it. Distinct from
`discovery` — which asks what is worth looking at *now* from price and strategy output — by
asking what is worth looking at *next*, from what companies and policy say.

Introduced by `theme-engine`.

## ADDED Requirements

### Requirement: A theme is evidenced by breadth and persistence, never by a single source
The system MUST require a theme to be referenced by more than one company and across more than
one period before surfacing it, and MUST publish both counts.

#### Scenario: A theme carries its counts
- GIVEN a surfaced theme
- WHEN it is read
- THEN the number of distinct companies referencing it and the number of periods it has
  persisted are both present

#### Scenario: One loud company is not a theme
- GIVEN a concept referenced by a single company in a single period
- WHEN themes are assembled
- THEN it is not surfaced

#### Scenario: A single period of broad noise is not a theme
- GIVEN a concept referenced by many companies within one period only
- WHEN themes are assembled
- THEN it is not surfaced as an established theme

#### Scenario: Every reference is traceable to its document
- GIVEN a theme's supporting references
- WHEN one is inspected
- THEN it names the company, the period and the source it came from

#### Scenario: A theme records which sources evidenced it
- GIVEN a theme assembled from commentary and policy
- WHEN it is read
- THEN the source kinds behind it are identifiable

### Requirement: Detection degrades to the sources that are available
The system MUST assemble themes from whichever sources answered, and MUST record which sources
were unavailable for that run.

#### Scenario: Unreadable documents do not stop detection
- GIVEN commentary documents that cannot be retrieved
- WHEN themes are assembled from policy and filings alone
- THEN themes are still produced
- AND the run records that commentary was unavailable

#### Scenario: No sources available produces nothing, not an empty claim
- GIVEN every source unavailable
- WHEN themes are assembled
- THEN no theme is surfaced
- AND the run is marked as having produced no reading rather than as finding nothing

### Requirement: A theme is expanded into a tiered chain of what it consumes
The system MUST expand a theme into ordered tiers of inputs, and each tier MUST record what it
depends on in the tier above it.

#### Scenario: Tiers are ordered by dependency
- GIVEN an expanded theme
- WHEN its chain is read
- THEN each tier beyond the first names the tier it supplies

#### Scenario: Every link carries its stated reasoning
- GIVEN a link between two tiers
- WHEN it is inspected
- THEN the reasoning offered for it is present and attributed to the model that proposed it

#### Scenario: A chain link is never a measurement
- GIVEN any link in a chain
- WHEN a verdict is produced for a company that link surfaced
- THEN no evidence row cites the link

#### Scenario: A link can be rejected
- GIVEN a link a reader judges wrong
- WHEN it is rejected
- THEN it no longer contributes candidates
- AND the rejection persists across later runs

#### Scenario: A rejected link is not silently re-proposed
- GIVEN a previously rejected link
- WHEN the theme is expanded again
- THEN the link is not reinstated without being shown as previously rejected

### Requirement: A theme may widen attention and may never narrow it
A theme MUST NOT exclude any instrument from screening or evaluation, MUST NOT alter a stance
or a conviction, and MUST NOT reorder any ranking.

#### Scenario: Every eligible name is still evaluated
- GIVEN a universe scan running with themes active
- WHEN it completes
- THEN every eligible instrument was evaluated by every strategy, exactly as without themes

#### Scenario: Verdicts are identical with themes on and off
- GIVEN the same instruments and the same price data
- WHEN verdicts are produced with themes active and again with themes disabled
- THEN the verdicts are identical

#### Scenario: A theme cannot remove a candidate
- GIVEN a candidate surfaced by a scan and unrelated to any theme
- WHEN themes are applied
- THEN it remains present

#### Scenario: No theme-derived score exists
- GIVEN the themes module
- WHEN it is searched for a value that scores or ranks instruments
- THEN none exists

#### Scenario: Theme membership is a label, not an ordering
- GIVEN candidates carrying theme labels
- WHEN they are ordered
- THEN the ordering rule is unchanged by the labels

### Requirement: Evidence and chains may be worldwide
The system MUST allow a theme to be evidenced by, and its chain to describe, activity outside
India, and MUST NOT require a reference or a tier to be domestic in order to be recorded.

#### Scenario: A theme evidenced from abroad still surfaces
- GIVEN references describing demand originating outside India
- WHEN themes are assembled
- THEN the theme surfaces on the same breadth and persistence rules

#### Scenario: A tier describing foreign activity is still recorded
- GIVEN a chain tier whose suppliers are predominantly foreign
- WHEN the chain is read
- THEN the tier is present with its reasoning rather than omitted

### Requirement: Only candidates are constrained to Indian listings
Every candidate the system offers MUST be an instrument in the platform's own universe, and a
tier with no such instrument MUST say so rather than offer a substitute.

#### Scenario: A tier without Indian exposure says so
- GIVEN a tier whose suppliers are not listed in India
- WHEN it is read
- THEN it is reported as having no Indian listed exposure
- AND no unrelated instrument is offered in its place

#### Scenario: Foreign suppliers explain a tier and are marked as not investable
- GIVEN a tier served by companies listed outside India
- WHEN it is read
- THEN those companies may be named as explanation
- AND each is marked as not offered as a candidate

#### Scenario: A foreign company is never a candidate
- GIVEN a tier whose reasoning names a foreign company
- WHEN candidates are collected
- THEN that company is absent from them

#### Scenario: An unresolvable supplier is recorded rather than guessed
- GIVEN a supplier description matching no instrument in the universe
- WHEN the tier is resolved
- THEN no candidate is produced for it
- AND the unresolved description is recorded

#### Scenario: Every candidate carries how it was matched
- GIVEN a resolved candidate
- WHEN it is read
- THEN the basis on which it matched is present and distinguishes a company that discussed the
  theme from one matched only by its industry

### Requirement: Exposure to a theme is graded, never asserted
Each candidate MUST carry how well its exposure to the theme is established, distinguishing
what disclosure supports from what management claims from what is unknown.

#### Scenario: Disclosure-supported exposure is established
- GIVEN a company whose segment disclosure covers the theme's activity
- WHEN its exposure is graded
- THEN it is graded as established, citing the disclosure

#### Scenario: A management claim is graded as claimed
- GIVEN a company whose commentary asserts exposure with no supporting disclosure
- WHEN its exposure is graded
- THEN it is graded as claimed, citing the commentary

#### Scenario: Unknown exposure is a displayable answer
- GIVEN a company with neither disclosure nor commentary on the theme
- WHEN its exposure is graded
- THEN it is graded as unestablished
- AND it is still listed

#### Scenario: A grade is never a number
- GIVEN a graded candidate
- WHEN it is read
- THEN the grade is a named category and carries no numeric strength

### Requirement: A theme that stops being evidenced is withdrawn
The system MUST withdraw a standing theme when a run re-assembles its sources and no longer
finds sufficient breadth and persistence, recording the reason.

#### Scenario: A faded theme is withdrawn with its reason
- GIVEN a standing theme
- WHEN a later run finds it referenced by too few companies
- THEN it is withdrawn and the reason names the shortfall

#### Scenario: Withdrawal keeps the history
- GIVEN a withdrawn theme
- WHEN withdrawn themes are requested
- THEN it is returned with its original first-seen date

#### Scenario: An unavailable source never withdraws a theme
- GIVEN a standing theme evidenced by commentary
- WHEN a run cannot retrieve any commentary
- THEN the theme is left standing rather than withdrawn

### Requirement: A theme run is recorded and reproducible in its deterministic parts
The system MUST persist each theme run with its inputs and its outputs, and the non-model parts
MUST produce the same result when re-run over the same inputs.

#### Scenario: A run is retrievable whole
- GIVEN a completed theme run
- WHEN it is requested
- THEN its themes, chains, candidates and unavailable sources are returned

#### Scenario: Counting is reproducible
- GIVEN the same source documents
- WHEN breadth and persistence are recomputed
- THEN the counts are identical

#### Scenario: The model's contribution is identified
- GIVEN a completed run
- WHEN it is read
- THEN the parts produced by a model are distinguishable from the parts counted by the platform

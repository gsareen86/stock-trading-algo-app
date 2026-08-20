# web-shell

## ADDED Requirements

### Requirement: Ideas answers where to look without being given a symbol
The Ideas surface MUST present market, sector and candidate information without requiring any
symbol input, and MUST NOT default to a fixed list of symbols.

#### Scenario: Ideas is useful with no input
- GIVEN the Ideas surface opened with no parameters
- WHEN it renders
- THEN market state, sector placement and the latest scan's candidates are shown

#### Scenario: No hard-coded symbol list exists
- GIVEN the Ideas surface source
- WHEN it is searched for a fixed default symbol list
- THEN none exists

#### Scenario: No scan yet
- GIVEN no scan has ever completed
- WHEN Ideas is opened
- THEN it says so and offers to run one
- AND it does not render an empty table as though nothing qualified

#### Scenario: A stale scan states its age
- GIVEN the latest scan is several days old
- WHEN Ideas is opened
- THEN the scan's date is shown alongside its results

### Requirement: A candidate leads to its own name
Every candidate shown on Ideas MUST link to the Stock surface for that instrument.

#### Scenario: A candidate is one click from its full reading
- GIVEN a candidate in the Ideas list
- WHEN it is followed
- THEN the Stock surface for that instrument opens

### Requirement: A plan is displayed with its basis
Where a plan is shown, each of its price levels MUST be reachable to the evidence it came from,
and a plan MUST NOT be shown for a strategy that published none.

#### Scenario: A plan level reaches its evidence
- GIVEN a displayed plan
- WHEN a price level is inspected
- THEN the evidence row it derives from is reachable

#### Scenario: No plan means no plan is shown
- GIVEN a verdict whose strategy published no plan
- WHEN the verdict is displayed
- THEN no entry, stop or target is rendered for it

#### Scenario: Plans stay attributed to their strategy
- GIVEN two strategies with plans for one instrument
- WHEN they are displayed
- THEN each plan appears within its own strategy's card

## MODIFIED Requirements

### Requirement: Six surfaces organised by intent
The web application MUST present its surfaces organised by the question each answers, and
**Ideas and Stock MUST answer different questions** — Ideas where to look, Stock everything
about one name.

#### Scenario: Each surface states its question
- GIVEN the navigation
- WHEN it is read
- THEN each surface carries the question it answers

#### Scenario: Ideas and Stock do not share their data path
- GIVEN the Ideas and Stock surfaces
- WHEN their data sources are compared
- THEN Ideas reads discovery output and Stock reads a single instrument's evaluation

#### Scenario: Stock requires a subject
- GIVEN the Stock surface opened with no symbol
- WHEN it renders
- THEN it asks for one
- AND it does not evaluate an arbitrary default

### Requirement: Surfaces never merge verdicts
A surface MUST NOT compute a value from more than one strategy's verdict, MUST NOT present a
consensus indicator, and MUST NOT order instruments by how many strategies agree. Where a
surface displays an ordered list, the figure it is ordered by MUST be attributed to one named
strategy.

#### Scenario: A ranked candidate names the strategy it is ranked by
- GIVEN a ranked list of candidates
- WHEN an entry is read
- THEN the conviction shown is attributed to one named strategy

#### Scenario: Agreement is shown as a count of stances, never as a score
- GIVEN a candidate on which three strategies say BUY
- WHEN it is displayed
- THEN the three stances are individually visible
- AND no combined figure is rendered

#### Scenario: No aggregation over verdict arrays
- GIVEN the surface sources with comments stripped
- WHEN they are searched for aggregation over arrays of verdicts
- THEN none is found

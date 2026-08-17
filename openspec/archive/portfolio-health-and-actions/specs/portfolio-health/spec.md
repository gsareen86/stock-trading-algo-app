# portfolio-health

## ADDED Requirements

### Requirement: Health scores portfolio structure, never instruments
The health score MUST be computed from properties of the book — concentration, diversification,
deployment and thesis integrity — and MUST NOT read a verdict, a stance or a conviction.

#### Scenario: No verdict reaches the score
- GIVEN the health modules
- WHEN their code is inspected
- THEN no reference to a verdict, stance or conviction appears

#### Scenario: No per-instrument score exists
- GIVEN the health modules
- WHEN searched for a function producing a per-instrument score or ranking
- THEN none exists

### Requirement: The headline is published with its components
The score MUST always be accompanied by each component's own score, weight, measurement and
threshold.

#### Scenario: Components accompany the headline
- GIVEN a health report
- WHEN it is read
- THEN every component appears with its measurement and threshold

#### Scenario: The headline is the weighted mean of components
- GIVEN component scores and weights
- WHEN the headline is computed
- THEN it equals their weighted mean

### Requirement: Components measure declared structural properties
Each component MUST measure one property against a declared threshold.

#### Scenario: Concentration penalises a dominant holding
- GIVEN a book dominated by one name
- WHEN concentration is scored
- THEN it scores lower than an evenly spread book

#### Scenario: Concentration is measured on cost, not market value
- GIVEN holdings whose market value has moved
- WHEN concentration is measured
- THEN the measurement reflects committed cost

#### Scenario: Deployment penalises both idle and fully committed books
- GIVEN a barely deployed book and a fully committed one
- WHEN deployment is scored
- THEN both score below a book deployed within the target band

#### Scenario: Thesis integrity weights by committed capital
- GIVEN a large holding whose buying strategy now says AVOID
- WHEN thesis integrity is scored
- THEN the measurement reflects that holding's share of committed capital

#### Scenario: An empty book is not penalised
- GIVEN no open positions
- WHEN health is scored
- THEN structural components do not report a problem

### Requirement: Guidance is attached to the component that produced it
Every guidance step MUST name its component, MUST be ordered by that component's weight, and
MUST NOT carry a score of its own.

#### Scenario: A concentrated book is told to trim
- GIVEN a holding above the concentration target
- WHEN guidance is produced
- THEN a trim step names that holding and the shares involved

#### Scenario: A broken thesis is told to exit
- GIVEN a holding whose buying strategy now says AVOID
- WHEN guidance is produced
- THEN an exit step names that holding

#### Scenario: Steps carry no score
- GIVEN guidance steps
- WHEN they are read
- THEN none carries a score

#### Scenario: Guidance never names what to buy
- GIVEN a book below the diversification target
- WHEN guidance is produced
- THEN it does not name an instrument to buy

#### Scenario: A healthy book produces no steps
- GIVEN every component above its guidance threshold
- WHEN guidance is produced
- THEN no steps are returned

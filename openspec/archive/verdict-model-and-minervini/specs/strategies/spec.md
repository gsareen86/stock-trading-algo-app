# strategies

## ADDED Requirements

### Requirement: Strategies are discovered by convention
The system MUST discover strategies from the strategies package without an explicit
registration list, and MUST record load failures rather than swallowing them.

#### Scenario: Registered strategy found
- GIVEN a strategy package exporting a definition
- WHEN the registry loads
- THEN that strategy is registered

#### Scenario: Broken strategy recorded
- GIVEN a strategy module that raises on import
- WHEN the registry loads
- THEN the failure is retrievable
- AND the remaining strategies still load

### Requirement: An unassessable instrument yields a verdict, not an error
When a strategy cannot assess an instrument, it MUST return a verdict whose hard gate failed,
rather than raising or returning nothing.

#### Scenario: Insufficient price history
- GIVEN an instrument with fewer bars than the longest moving average requires
- WHEN the strategy evaluates it
- THEN a verdict is returned with stance `AVOID`
- AND a failing history gate explains why

#### Scenario: No price data at all
- GIVEN an instrument the price source has no data for
- WHEN the strategy evaluates it
- THEN a verdict is returned with a failing gate rather than an exception

#### Scenario: Untraded instrument
- GIVEN an instrument whose recent volume is zero throughout
- WHEN the strategy evaluates it
- THEN a failing liquidity gate is recorded

### Requirement: The Trend Template is evaluated in full
The Minervini strategy MUST evaluate all eight Trend Template criteria and emit one evidence
row per criterion.

#### Scenario: Every criterion produces evidence
- GIVEN an instrument with sufficient history
- WHEN the strategy evaluates it
- THEN eight evidence rows corresponding to the criteria are present
- AND each records its observed value, threshold and pass state

#### Scenario: A stock in a confirmed uptrend passes the template
- GIVEN a price series trending steadily upward near its 52-week high
- WHEN the strategy evaluates it
- THEN all eight criteria pass

#### Scenario: A stock below its long moving averages fails
- GIVEN a price series in a sustained downtrend
- WHEN the strategy evaluates it
- THEN the criteria comparing price to its moving averages fail
- AND the stance is not `BUY`

### Requirement: Trend Template criteria are scored, not gated
Failing a Trend Template criterion MUST reduce conviction rather than force `AVOID`.

#### Scenario: Partial template yields a watch
- GIVEN a series passing most but not all criteria with gates intact
- WHEN the strategy evaluates it
- THEN the stance is `WATCH` rather than `AVOID`
- AND conviction is below that of a full pass

### Requirement: Relative strength is measured against a benchmark and named as such
The relative-strength criterion MUST compare the instrument's return against a benchmark index
over the same window, and MUST NOT be labelled as a cross-sectional RS Rating.

#### Scenario: Outperformance passes
- GIVEN an instrument outperforming the benchmark over the lookback
- WHEN the criterion is evaluated
- THEN it passes
- AND the evidence reports the relative percentage

#### Scenario: The field is not called a rating
- GIVEN the relative-strength evidence row
- WHEN its label and fields are inspected
- THEN they identify it as benchmark-relative, not as an RS Rating percentile

#### Scenario: Benchmark unavailable
- GIVEN no benchmark price history
- WHEN the criterion is evaluated
- THEN it is recorded as not passed with the reason stated
- AND the evaluation still produces a verdict

### Requirement: VCP contractions are detected and quantified
The strategy MUST report the number of successive contractions and their depths.

#### Scenario: Successive tightening contractions
- GIVEN a base of pullbacks each shallower than the last
- WHEN contractions are analysed
- THEN their count and depths are reported as evidence

#### Scenario: No base present
- GIVEN a series with no contraction structure
- WHEN contractions are analysed
- THEN zero contractions are reported
- AND no exception is raised

#### Scenario: Too few contractions lowers quality rather than rejecting
- GIVEN a base with a single contraction
- WHEN the verdict is formed
- THEN VCP quality is reduced
- AND the stance is not forced to `AVOID` for that reason alone

### Requirement: Conviction is derived from a stated formula
Conviction MUST be computed from the criteria passed and VCP quality, and MUST be reproducible
from the evidence alone.

#### Scenario: Full template with a strong base scores high
- GIVEN all criteria passing and multiple tightening contractions
- WHEN the verdict is formed
- THEN conviction is at least the buy threshold

#### Scenario: Same bars give the same conviction
- GIVEN the same price series evaluated twice
- WHEN conviction is computed
- THEN both values are identical

#### Scenario: Conviction never leaves its range
- GIVEN any evaluated instrument
- WHEN the verdict is formed
- THEN conviction is between 0 and 100 inclusive

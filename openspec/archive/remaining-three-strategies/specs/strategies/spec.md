# strategies

## ADDED Requirements

### Requirement: Four independent strategies are registered
The registry MUST provide `minervini`, `brahma_vishnu_mahesh`, `fun_tech_momentum` and
`young_momentum`.

#### Scenario: All four discoverable
- GIVEN the registry has loaded
- WHEN registered ids are listed
- THEN all four are present with no load failures

#### Scenario: Each produces its own verdict for one instrument
- GIVEN one instrument
- WHEN every strategy evaluates it
- THEN four verdicts are produced, each carrying its own stance, conviction and evidence

#### Scenario: Disagreement is preserved
- GIVEN price and fundamental data that suits one strategy and not another
- WHEN all four evaluate the same instrument
- THEN their stances may differ
- AND no combined stance, score or agreement count is produced anywhere

### Requirement: Market regime is scored, not gated
A hostile market regime MUST reduce conviction rather than force `AVOID`.

#### Scenario: Bearish regime lowers conviction
- GIVEN a benchmark below a falling long-term weekly average
- WHEN Brahma-Vishnu-Mahesh evaluates an otherwise strong instrument
- THEN the regime criterion fails
- AND conviction is materially lower than under a bullish regime

#### Scenario: Bearish regime does not fail a gate
- GIVEN a bearish regime and an assessable instrument
- WHEN the verdict is formed
- THEN its gates still pass
- AND the stance is decided by conviction, not by the regime alone

### Requirement: Sector strength is evaluated against peer sector indices
Brahma-Vishnu-Mahesh MUST rank the instrument's sector index against the other sector indices
on relative strength against the benchmark.

#### Scenario: Leading sector passes
- GIVEN the instrument's sector index outperforming the others
- WHEN the sector criterion is evaluated
- THEN it passes and its rank is recorded

#### Scenario: Lagging sector fails
- GIVEN the instrument's sector index ranked outside the leaders
- WHEN the criterion is evaluated
- THEN it does not pass

#### Scenario: Unknown sector is recorded, not skipped
- GIVEN an instrument whose sector cannot be resolved
- WHEN the criterion is evaluated
- THEN it is recorded as not passed with the reason stated
- AND the criterion still appears in the evidence

### Requirement: A multi-year breakout requires range and volume together
Brahma-Vishnu-Mahesh MUST require both a breakout from a long horizontal range and a volume
expansion.

#### Scenario: Breakout on expanding volume
- GIVEN a price emerging above a multi-year range on volume far above its average
- WHEN the criterion is evaluated
- THEN it passes

#### Scenario: Breakout without volume
- GIVEN a price emerging above the range on ordinary volume
- WHEN the criterion is evaluated
- THEN the volume component does not pass

### Requirement: Fundamentals are a gate for the fundamental strategy
`fun_tech_momentum` MUST fail a hard gate when quarterly fundamentals are unavailable.

#### Scenario: No fundamentals available
- GIVEN a fundamentals source with no data for the instrument
- WHEN the strategy evaluates it
- THEN the stance is `AVOID` with a failing fundamentals gate
- AND the reason states that the screen cannot be run

#### Scenario: Fundamentals present allows evaluation
- GIVEN sufficient quarterly history
- WHEN the strategy evaluates the instrument
- THEN gates pass and the fundamental criteria are scored

#### Scenario: Other strategies do not require fundamentals
- GIVEN no fundamentals source at all
- WHEN the price-only strategies evaluate an instrument
- THEN their gates still pass

### Requirement: The earnings surprise test is satisfied by either line
`fun_tech_momentum` MUST treat accelerating EPS **or** accelerating revenue as satisfying the
surprise criterion, and MUST record which one did.

#### Scenario: EPS acceleration alone passes
- GIVEN EPS at least 1.5× the year-ago quarter and flat revenue
- WHEN the criterion is evaluated
- THEN it passes and the evidence names EPS

#### Scenario: Revenue acceleration alone passes
- GIVEN revenue at least 1.5× the year-ago quarter and flat EPS
- WHEN the criterion is evaluated
- THEN it passes and the evidence names revenue

#### Scenario: Neither accelerating fails
- GIVEN both lines roughly flat year on year
- WHEN the criterion is evaluated
- THEN it does not pass

#### Scenario: Year-ago comparison uses the same quarter
- GIVEN four quarters of seasonal results
- WHEN the surprise is computed
- THEN the latest quarter is compared with the same quarter one year earlier

### Requirement: Young Momentum requires a shallow pause after an impulse
`young_momentum` MUST require an impulse leg followed by a pause that does not retrace beyond
the 38.2% Fibonacci level of that impulse.

#### Scenario: Shallow pause passes
- GIVEN an impulse of 30% followed by a three-day pause retracing under 38.2%
- WHEN the criterion is evaluated
- THEN it passes

#### Scenario: Deep retracement fails
- GIVEN a pause retracing beyond the 38.2% level
- WHEN the criterion is evaluated
- THEN it does not pass
- AND the observed retracement is recorded against the threshold

#### Scenario: No impulse present
- GIVEN a series with no qualifying impulse leg
- WHEN the strategy evaluates it
- THEN the impulse criterion does not pass
- AND a verdict is still produced

### Requirement: Entry levels are informational, not decisions
A strategy emitting a trigger or stop level MUST record it as informational evidence.

#### Scenario: Trigger recorded without a pass state
- GIVEN a qualifying continuation setup
- WHEN the entry trigger is emitted
- THEN it is informational evidence with no pass state
- AND no position size appears in the verdict

### Requirement: Each strategy has its own conviction formula
Conviction MUST be computed per strategy from its own criteria, and MUST NOT share a scale
across strategies.

#### Scenario: Same instrument, different convictions
- GIVEN one instrument evaluated by all four strategies
- WHEN their convictions are compared
- THEN each is derived from its own criteria

#### Scenario: Conviction reproducible per strategy
- GIVEN identical inputs evaluated twice by any strategy
- WHEN conviction is computed
- THEN both values are identical

#### Scenario: Conviction always within range
- GIVEN any instrument and any of the four strategies
- WHEN the verdict is formed
- THEN conviction is between 0 and 100 inclusive

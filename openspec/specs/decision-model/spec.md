# decision-model

Verdicts, evidence and gates — the rules that keep per-strategy opinions independent and every claim traceable.

Introduced by `verdict-model-and-minervini` (see `openspec/archive/`).

### Requirement: A failed hard gate forces AVOID
A `Verdict` with any failing hard gate MUST have stance `AVOID`, and MUST NOT be constructible
with any other stance.

#### Scenario: Failing gate with high conviction
- GIVEN a verdict whose liquidity gate failed
- AND a conviction of 90
- WHEN the verdict is constructed with stance `BUY`
- THEN construction is rejected

#### Scenario: All gates pass
- GIVEN a verdict whose gates all pass
- WHEN it is constructed with stance `BUY`
- THEN construction succeeds

#### Scenario: Conviction is not suppressed by the gate
- GIVEN a verdict with a failing gate
- WHEN it is constructed with stance `AVOID` and conviction 90
- THEN construction succeeds
- AND the conviction remains 90, recorded separately from the gate outcome

### Requirement: Verdicts are never blended
The system MUST NOT provide any operation that combines verdicts from different strategies
into a single stance, score or ranking.

#### Scenario: No cross-strategy aggregation exists
- GIVEN the decision-model module
- WHEN its public surface is inspected
- THEN it exposes no function combining multiple verdicts into one

#### Scenario: Multiple verdicts for one ticker coexist
- GIVEN two strategies producing different stances for the same ticker
- WHEN both verdicts are stored
- THEN both are retained with their own stance and conviction

### Requirement: Conviction is scoped to one strategy
Conviction MUST be an integer from 0 to 100 that is meaningful only within its own strategy.

#### Scenario: Out-of-range conviction rejected
- GIVEN a conviction of 140
- WHEN a verdict is constructed
- THEN construction is rejected

#### Scenario: Strategy recorded alongside conviction
- GIVEN any verdict
- WHEN it is read
- THEN its strategy id is present, so the conviction is never interpretable on its own

### Requirement: Every verdict carries evidence
A `Verdict` MUST carry at least one `Evidence` row.

#### Scenario: Empty evidence rejected
- GIVEN a verdict with no evidence
- WHEN it is constructed
- THEN construction is rejected

### Requirement: Evidence identifiers are unique within a verdict
Evidence ids MUST be unique, so a citation is unambiguous.

#### Scenario: Duplicate ids rejected
- GIVEN two evidence rows sharing an id
- WHEN a verdict is constructed
- THEN construction is rejected naming the duplicate

### Requirement: Gates cite evidence that exists
Every `GateResult` MUST reference evidence ids present on the same verdict.

#### Scenario: Gate cites a missing row
- GIVEN a gate referencing an evidence id no row carries
- WHEN the verdict is constructed
- THEN construction is rejected naming the missing id

#### Scenario: Gate cites present rows
- GIVEN a gate referencing ids that exist
- WHEN the verdict is constructed
- THEN construction succeeds

### Requirement: Evidence records the comparison, not just the value
Each `Evidence` row MUST carry its observed value, and where it is a test, the threshold and
operator that were applied.

#### Scenario: Threshold test recorded in full
- GIVEN a criterion testing price against a moving average
- WHEN its evidence is emitted
- THEN the row carries the observed value, the threshold, the operator and whether it passed

#### Scenario: Informational rows carry no false threshold
- GIVEN a contextual measurement that is not a test
- WHEN its evidence is emitted
- THEN its operator is informational and `passed` is null

### Requirement: Every evidence row is traceable
Each `Evidence` row MUST carry a non-empty `source_ref`.

#### Scenario: Missing source rejected
- GIVEN an evidence row with an empty source reference
- WHEN it is constructed
- THEN construction is rejected

### Requirement: A verdict is complete without a narrative
A `Verdict` MUST be valid with a null narrative, and its stance and conviction MUST be
reproducible without any language model. Attaching a narrative MUST be the only mutation the
type permits, and MUST reach no field other than the narrative and the trace id.

#### Scenario: Verdict valid with no narrative
- GIVEN a verdict whose narrative is null
- WHEN it is constructed
- THEN construction succeeds

#### Scenario: Same inputs produce the same verdict
- GIVEN identical price history evaluated twice
- WHEN a strategy runs
- THEN both verdicts have the same stance, conviction and evidence values

#### Scenario: Attaching a narrative changes nothing else
- GIVEN a verdict
- WHEN a narrative is attached to it
- THEN stance, conviction, gates and evidence are unchanged
- AND no other mutator exists on the type

### Requirement: Verdicts round-trip through storage
A stored verdict MUST be retrievable with its stance, conviction, gates and evidence intact.

#### Scenario: Save and reload
- GIVEN a verdict with gates and evidence
- WHEN it is saved and loaded
- THEN the reloaded verdict matches the original

#### Scenario: Stored verdicts are queryable by ticker
- GIVEN verdicts stored for several tickers
- WHEN verdicts for one ticker are requested
- THEN only that ticker's verdicts are returned

### Requirement: A verdict exposes the numbers a narrative may cite
A `Verdict` MUST expose the set of figures that prose about it is permitted to state, derived
from its own contents rather than from a fixed list of allowed constants.

#### Scenario: Measured values and thresholds included
- GIVEN a verdict with evidence carrying values and thresholds
- WHEN its citable numbers are read
- THEN both appear in the set

#### Scenario: Numbers naming a metric included
- GIVEN an evidence row whose label names a 200-day average
- WHEN its citable numbers are read
- THEN 200 appears in the set

#### Scenario: Conviction included
- GIVEN a verdict with a conviction
- WHEN its citable numbers are read
- THEN the conviction appears in the set

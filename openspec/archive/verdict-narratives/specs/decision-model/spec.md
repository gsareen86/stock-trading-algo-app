# decision-model

## MODIFIED Requirements

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

## ADDED Requirements

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

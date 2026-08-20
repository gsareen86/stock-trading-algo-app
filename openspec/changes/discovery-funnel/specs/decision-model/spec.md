# decision-model

## ADDED Requirements

### Requirement: A strategy publishes the plan implied by its own verdict
A strategy producing an actionable verdict MUST also publish the entry, stop, target and
expected holding period that its own method implies, or state that it has no basis for one.

#### Scenario: Every plan figure traces to evidence
- GIVEN a plan attached to a verdict
- WHEN each of its price levels is read
- THEN each cites an evidence row from that same verdict

#### Scenario: A strategy with no basis publishes no plan
- GIVEN a strategy whose method implies no exit rule for a verdict
- WHEN the verdict is produced
- THEN no plan is attached
- AND the absence is stated rather than filled with a default

#### Scenario: The holding period is expressed as the method's own horizon
- GIVEN a plan from a strategy whose exit is a moving-average break
- WHEN the holding period is read
- THEN it is expressed as that condition and its typical duration, not as a fixed date

#### Scenario: A plan is absent from an AVOID verdict
- GIVEN a verdict whose stance is AVOID
- WHEN it is read
- THEN no entry plan is attached

#### Scenario: Plans are never combined across strategies
- GIVEN two strategies publishing plans for the same instrument
- WHEN they are read
- THEN both are present separately
- AND no merged entry, stop or target is computed

#### Scenario: A plan is produced without a model
- GIVEN narration disabled
- WHEN a verdict with a plan is produced
- THEN the plan is present and identical to the narrated case

#### Scenario: A plan proposes and never acts
- GIVEN a verdict carrying a plan
- WHEN the verdict is produced, stored or displayed
- THEN no trade is recorded

### Requirement: A plan's risk and reward are stated in the same terms
A plan MUST express the distance from entry to stop and from entry to target in both absolute
and percentage terms, and MUST state their ratio.

#### Scenario: Both distances and the ratio are present
- GIVEN a plan with an entry, a stop and a target
- WHEN it is read
- THEN both distances appear in rupees and in percent, with their ratio

#### Scenario: A plan without a target has no ratio
- GIVEN a plan whose strategy defines an exit condition but no price target
- WHEN it is read
- THEN the risk distance is present and no ratio is claimed

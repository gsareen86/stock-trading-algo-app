# verdict-narratives

Turning a verdict's evidence into plain English, with every number in the prose traceable to a
row the verdict established.

Introduced by `verdict-narratives` (see `openspec/archive/`).

### Requirement: A narrative may state only numbers the verdict established
Generated prose MUST NOT contain a figure that cannot be traced to the verdict. The traceable
set MUST include evidence values, evidence thresholds, numbers appearing in an evidence label
or id, and the conviction.

#### Scenario: Invented figure rejected
- GIVEN a verdict whose evidence contains no figure near 47.2
- WHEN a generated narrative states "up 47.2% this year"
- THEN the narrative is rejected
- AND the rejection names the untraceable figure

#### Scenario: Rounded value accepted
- GIVEN an evidence value of 12.437
- WHEN a narrative states 12.4
- THEN the narrative is accepted

#### Scenario: Truncated value accepted
- GIVEN an evidence value of 5.2968
- WHEN a narrative states 5.29
- THEN the narrative is accepted

#### Scenario: Nearby value rejected
- GIVEN an evidence value of 12.437
- WHEN a narrative states 12.5
- THEN the narrative is rejected

#### Scenario: Number from a metric's own name accepted
- GIVEN an evidence row labelled for a 200-day moving average
- WHEN a narrative refers to the 200-day moving average
- THEN the narrative is accepted
- AND the figure is not treated as an invented measurement

#### Scenario: Small figures have no exemption
- GIVEN a verdict whose evidence contains no figure near 2
- WHEN a narrative states "the stock is up 2% today"
- THEN the narrative is rejected

### Requirement: Cited evidence must exist
A narrative MUST cite evidence by id, and every cited id MUST exist on the verdict.

#### Scenario: Unknown citation rejects the narrative
- GIVEN a narrative citing an evidence id absent from the verdict
- WHEN it is validated
- THEN the narrative is rejected
- AND the rejection names the unknown id

#### Scenario: Citation identifiers are not read as measurements
- GIVEN a narrative citing an evidence id containing digits
- WHEN it is validated
- THEN those digits are not required to trace to an evidence value

### Requirement: A rejected narrative is discarded whole
The system MUST NOT publish a partially corrected narrative, and MUST NOT retry generation to
obtain a passing one.

#### Scenario: Rejection leaves no prose
- GIVEN a narrative failing validation
- WHEN generation completes
- THEN the verdict carries no narrative
- AND no sentence of the rejected text is published

#### Scenario: Rejection is reported, not raised
- GIVEN a narrative failing validation
- WHEN it was requested through the API
- THEN the response succeeds
- AND the outcome for that verdict is reported as rejected

### Requirement: Narration cannot alter a verdict
Attaching a narrative MUST change only the narrative and trace id. Stance, conviction, gates
and evidence MUST be identical to the verdict before narration.

#### Scenario: Decision fields untouched
- GIVEN a verdict with a failed gate and stance AVOID
- WHEN a narrative is generated and attached
- THEN stance, conviction, gates and evidence are unchanged

#### Scenario: Verdict is unchanged when no model answers
- GIVEN the gateway returns no result
- WHEN narration is attempted
- THEN the verdict is returned exactly as it was
- AND no exception reaches the caller

### Requirement: The model receives evidence, never raw market data
The narrative prompt MUST carry only the verdict's evidence, gates, stance and conviction. It
MUST NOT carry price series or other source data from which a new figure could be derived.

#### Scenario: No price series in the prompt
- GIVEN a verdict built from a price history
- WHEN the narrative prompt is constructed
- THEN it contains no price series

#### Scenario: Stance is presented as decided
- GIVEN a verdict with a stance
- WHEN the prompt is constructed
- THEN the stance is stated as a fact to explain rather than a question to answer

### Requirement: Explanation guidance is per strategy and versioned
The system MUST provide explanation guidance per strategy, stored as editable content rather
than code, and MUST fall back to shared guidance when a strategy has none.

#### Scenario: Strategy guidance selected
- GIVEN a verdict from a strategy with its own guidance
- WHEN the prompt is built
- THEN that strategy's vocabulary appears in the instructions

#### Scenario: Unknown strategy still explainable
- GIVEN a strategy with no guidance file
- WHEN the prompt is built
- THEN the shared rules are used
- AND generation is not blocked

### Requirement: Presentation is requested, not enforced
The system MUST validate a narrative's factual claims only. It MUST NOT reject or rewrite a
narrative for failing to follow formatting guidance.

#### Scenario: Ill-formatted but accurate narrative is published
- GIVEN a narrative whose every figure traces to the evidence
- AND which ignores the requested paragraph and formatting shape
- WHEN it is validated
- THEN it is accepted

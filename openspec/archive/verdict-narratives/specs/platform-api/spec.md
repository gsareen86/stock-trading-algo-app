# platform-api

## MODIFIED Requirements

### Requirement: Instruments can be evaluated on demand
`POST /verdicts/evaluate` MUST evaluate named instruments and return one verdict per strategy
per instrument. Narration MUST be opt-in and MUST NOT be attempted unless requested.

#### Scenario: Evaluation returns verdicts with evidence
- GIVEN a symbol with price history
- WHEN evaluation is requested
- THEN a verdict is returned carrying stance, conviction, gates and evidence

#### Scenario: Verdicts are returned per strategy, never merged
- GIVEN more than one registered strategy
- WHEN a symbol is evaluated
- THEN one verdict per strategy is returned
- AND no combined stance or score appears in the response

#### Scenario: Evaluation does not persist by default
- GIVEN an evaluation request without a persist flag
- WHEN it completes
- THEN no verdict is written to storage

#### Scenario: Persisting is explicit
- GIVEN an evaluation request asking to persist
- WHEN it completes
- THEN the verdicts are retrievable afterwards

#### Scenario: Narration is off by default
- GIVEN an evaluation request without a narrate flag
- WHEN it completes
- THEN no language model is called
- AND every returned verdict has a null narrative

#### Scenario: Unknown strategy requested
- GIVEN a strategy id no strategy declares
- WHEN evaluation is requested for it
- THEN the response is a validation error naming the unknown id

## ADDED Requirements

### Requirement: Narration outcomes are reported per verdict
When narration is requested, the response MUST report an outcome for each verdict, so an
absent narrative is distinguishable from one that was never requested.

#### Scenario: Successful narration reported
- GIVEN narration is requested and validation passes
- WHEN the response is returned
- THEN the outcome for that verdict is reported as successful
- AND the verdict carries prose

#### Scenario: Rejected narrative does not fail the request
- GIVEN a generated narrative containing an untraceable figure
- WHEN the response is returned
- THEN the request succeeds
- AND that verdict's outcome names the rejection

#### Scenario: Unavailable model does not cost the caller their verdicts
- GIVEN no language model answers
- WHEN narration was requested
- THEN the verdicts are still returned
- AND each outcome reports the model as unavailable

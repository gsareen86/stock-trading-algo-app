# platform-api

## ADDED Requirements

### Requirement: Registered strategies are listable
`GET /strategies` MUST return the registered strategies with their identity and any load
failures.

#### Scenario: Strategies listed
- GIVEN the registry has loaded
- WHEN `GET /strategies` is requested
- THEN each strategy is returned with its id, name and description

#### Scenario: Load failures surfaced
- GIVEN a strategy module that failed to import
- WHEN `GET /strategies` is requested
- THEN that failure appears in the response

### Requirement: Instruments can be evaluated on demand
`POST /verdicts/evaluate` MUST evaluate named instruments and return one verdict per strategy
per instrument.

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

#### Scenario: Unknown strategy requested
- GIVEN a strategy id no strategy declares
- WHEN evaluation is requested for it
- THEN the response is a validation error naming the unknown id

### Requirement: Stored verdicts are listable
`GET /verdicts` MUST return stored verdicts, most recent first, filterable by ticker and
strategy.

#### Scenario: Filtered by ticker
- GIVEN stored verdicts for several tickers
- WHEN verdicts are requested for one ticker
- THEN only that ticker's verdicts are returned

#### Scenario: Newest first
- GIVEN several stored verdicts
- WHEN they are listed
- THEN they are ordered most recent first

#### Scenario: Bounded page size
- GIVEN a request for more verdicts than the permitted maximum
- WHEN it is made
- THEN the response is a validation error naming the limit

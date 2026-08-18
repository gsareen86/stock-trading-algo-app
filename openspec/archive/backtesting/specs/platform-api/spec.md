# platform-api

## ADDED Requirements

### Requirement: A replay can be run on demand
`POST /backtest/run` MUST replay the strategies over a requested window and return per-strategy
results together with the run's stated biases.

#### Scenario: A replay returns results and biases
- GIVEN a valid window and symbols
- WHEN a replay is requested
- THEN per-strategy results and the bias report are returned

#### Scenario: An inverted window is rejected
- GIVEN an end date before the start date
- WHEN a replay is requested
- THEN the response is a validation error

#### Scenario: A replay requires authentication
- GIVEN no credentials
- WHEN a replay is requested
- THEN it is rejected

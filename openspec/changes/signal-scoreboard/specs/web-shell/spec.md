# web-shell

## ADDED Requirements

### Requirement: Performance shows whether signals worked
The Performance surface MUST show the signal scoreboard per strategy, one holding period at a
time, with the measured count, mean return, mean excess with its standard error, median excess,
share beating the benchmark and share of stops touched.

#### Scenario: A holding period is chosen
- GIVEN the scoreboard measured 5, 20 and 60 sessions
- WHEN a reader selects 60 sessions
- THEN every strategy's rows show the 60-session figures

#### Scenario: Thin rows are marked
- GIVEN a row below the thin-sample floor
- WHEN it is shown
- THEN it carries a visible thin marker

#### Scenario: Unreachable backend
- GIVEN the scoreboard cannot be fetched
- WHEN Performance renders
- THEN the unavailable state is shown and the book sections still render

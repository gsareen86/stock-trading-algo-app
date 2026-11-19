# platform-api

## MODIFIED Requirements

### Requirement: A replay can be requested over HTTP within interactive bounds
The API MUST accept a replay request naming symbols, a window and the replay's options (entry
mode, order validity, chase limit, hold limit, cost, slippage, benchmark), MUST refuse more than
100 symbols or a window longer than three years, and MUST run the replay without blocking other
requests.

#### Scenario: Options reach the run
- GIVEN a request with entry mode, cost and symbols
- WHEN the replay runs
- THEN the report's configuration and cost model carry those values
- AND each symbol's sector is supplied where known

#### Scenario: A long window belongs on the command line
- GIVEN a request spanning more than three years
- WHEN it is submitted
- THEN it is refused with a validation error

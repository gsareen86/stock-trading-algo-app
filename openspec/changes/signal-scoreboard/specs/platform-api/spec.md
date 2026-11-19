# platform-api

## ADDED Requirements

### Requirement: The signal scoreboard is readable
The API MUST expose the signal scoreboard at `GET /discovery/scoreboard`, accepting the signal
filter (`new` or `all`), an optional strategy, holding periods and a scan count.

#### Scenario: Defaults answer with new signals at 5, 20 and 60 sessions
- GIVEN an authenticated caller and completed scans
- WHEN the scoreboard is requested with no parameters
- THEN it reports new signals at 5, 20 and 60 sessions

#### Scenario: Invalid parameters are refused
- GIVEN a signal filter other than `new` or `all`, or holding periods that are not integers
- WHEN the scoreboard is requested
- THEN the request is refused with a validation error

#### Scenario: A repeated request does not recompute
- GIVEN a scoreboard already computed today for the latest completed scan and these parameters
- WHEN the same request arrives without `refresh`
- THEN the earlier result is returned

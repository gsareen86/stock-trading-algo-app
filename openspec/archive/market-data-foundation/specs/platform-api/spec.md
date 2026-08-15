# platform-api

## ADDED Requirements

### Requirement: Health reports trading-calendar coverage
`GET /health` MUST report the range of years the NSE holiday data covers and whether the
current year is among them.

#### Scenario: Current year covered
- GIVEN holiday data covering the current year
- WHEN `GET /health` is requested
- THEN the calendar section reports the covered years and `current_year_covered` true

#### Scenario: Holiday data has run out
- GIVEN holiday data whose latest year is before the current year
- WHEN `GET /health` is requested
- THEN `current_year_covered` is false
- AND overall `status` is `degraded`

#### Scenario: Stale calendar does not fail the request
- GIVEN holiday data that does not cover the current year
- WHEN `GET /health` is requested
- THEN the response status is still 200

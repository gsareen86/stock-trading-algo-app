# market-calendar

## ADDED Requirements

### Requirement: Trading days exclude weekends and NSE holidays
The system MUST treat a date as a trading day only when it is a weekday and not an NSE
full-day holiday.

#### Scenario: Ordinary weekday
- GIVEN a Tuesday that is not a holiday and whose year is covered
- WHEN the date is checked
- THEN it is a trading day

#### Scenario: Weekend
- GIVEN a Saturday in a covered year
- WHEN the date is checked
- THEN it is not a trading day

#### Scenario: Published holiday
- GIVEN a weekday listed as an NSE holiday
- WHEN the date is checked
- THEN it is not a trading day

### Requirement: Holidays are data, not code
NSE holidays MUST be stored in a data file, so a yearly update requires no code change.

#### Scenario: Adding a year requires no code change
- GIVEN a new year's holidays added to the data file
- WHEN the calendar is loaded
- THEN those dates are recognised as holidays
- AND no Python module was modified

### Requirement: An uncovered year is refused, never assumed open
The calendar MUST raise rather than answer when asked about a year its data does not cover.

#### Scenario: Year beyond the data
- GIVEN the holiday data covers 2026 only
- WHEN a 2027 date is checked
- THEN a `CalendarNotCovered` error is raised naming the year
- AND the date is not reported as a trading day

#### Scenario: Coverage is queryable before asking
- GIVEN the holiday data covers 2026
- WHEN coverage for 2026 is queried
- THEN it reports covered
- AND coverage for 2027 reports not covered

### Requirement: Market session hours are IST
The system MUST evaluate whether the market is open against the 09:15–15:30 IST session on a
trading day.

#### Scenario: Mid-session
- GIVEN 11:00 IST on a trading day
- WHEN the market state is checked
- THEN the market is open

#### Scenario: Before the open
- GIVEN 09:00 IST on a trading day
- WHEN the market state is checked
- THEN the market is not open

#### Scenario: After the close
- GIVEN 15:45 IST on a trading day
- WHEN the market state is checked
- THEN the market is not open

#### Scenario: Session hours on a holiday
- GIVEN 11:00 IST on a published holiday
- WHEN the market state is checked
- THEN the market is not open

#### Scenario: UTC instant converted before evaluation
- GIVEN an instant expressed in UTC that falls inside the IST session
- WHEN the market state is checked
- THEN it is evaluated against IST, not the supplied zone

### Requirement: The most recent trading day is resolvable
The system MUST be able to report the latest trading day on or before a given date, for
"as of" stamping.

#### Scenario: Asked on a trading day
- GIVEN a Tuesday that is a trading day
- WHEN the most recent trading day on or before it is requested
- THEN that Tuesday is returned

#### Scenario: Asked on a weekend
- GIVEN a Sunday preceded by a normal trading week
- WHEN the most recent trading day on or before it is requested
- THEN the preceding Friday is returned

#### Scenario: Asked after a long holiday weekend
- GIVEN a Monday holiday following a weekend
- WHEN the most recent trading day on or before that Monday is requested
- THEN the preceding Friday is returned

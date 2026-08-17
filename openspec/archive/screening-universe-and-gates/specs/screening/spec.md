# screening

## ADDED Requirements

### Requirement: Screening decides eligibility, never merit
A screen MUST return eligible instruments in universe order and MUST NOT rank, sort or score
them by any measure of quality.

#### Scenario: Universe order preserved
- GIVEN a universe listing instruments in a given order
- WHEN they are screened
- THEN the eligible ones are returned in that same order

#### Scenario: A limit truncates rather than selects
- GIVEN more eligible instruments than the requested limit
- WHEN the limit is applied
- THEN the first instruments in universe order are kept
- AND the remainder are recorded as excluded by the limit

#### Scenario: No ranking function exists
- GIVEN the screening module
- WHEN it is searched for a function that ranks or scores instruments
- THEN none exists

### Requirement: Liquidity is measured as turnover in rupees
Screening MUST measure liquidity as median daily turnover in rupees over a lookback window,
and MUST NOT decide liquidity from share count alone.

#### Scenario: Thin stock fails
- GIVEN an instrument trading a handful of shares a day
- WHEN it is screened against a turnover floor
- THEN it is excluded

#### Scenario: Median resists a single large day
- GIVEN an instrument with one very large session and otherwise negligible volume
- WHEN its turnover is measured
- THEN the measure reflects the typical session, not the outlier
- AND the instrument is excluded

#### Scenario: Equal share counts at different prices are not equivalent
- GIVEN two instruments trading the same number of shares at prices differing by orders of magnitude
- WHEN their turnover is measured
- THEN the measures differ proportionally to price

### Requirement: Every exclusion carries its reason and measurement
An excluded instrument MUST record the filter that removed it, the value measured, the
threshold applied where one exists, and a source reference.

#### Scenario: Exclusion names its filter and value
- GIVEN an instrument excluded by a screen
- WHEN the result is read
- THEN the filter, the measured value and a source reference are present

#### Scenario: Counts per filter are reported
- GIVEN a screen that excluded instruments for several different reasons
- WHEN the result is read
- THEN a count per filter is available
- AND a small result is diagnosable without re-running the screen

#### Scenario: Unavailable price history is an exclusion, not a failure
- GIVEN an instrument whose price history cannot be fetched
- WHEN it is screened
- THEN it is excluded with that as its recorded reason
- AND the screen completes

### Requirement: Instruments under exchange surveillance are excluded
The system MUST exclude instruments under an NSE surveillance measure from a screen, and MUST
report which measure applied.

#### Scenario: Listed instrument excluded
- GIVEN an instrument on the ASM or GSM list
- WHEN it is screened
- THEN it is excluded
- AND the measure is named in the reason

#### Scenario: Surveillance costs no price fetch
- GIVEN an instrument under surveillance
- WHEN it is screened
- THEN no price history is requested for it

### Requirement: Surveillance data reports its own age
The surveillance list MUST record when it was last updated, and a screen MUST report whether
that data is stale.

#### Scenario: Stale list is reported
- GIVEN a surveillance list older than the staleness threshold
- WHEN a screen runs
- THEN the result reports the data as stale

#### Scenario: Unknown age counts as stale
- GIVEN a surveillance list with no recorded date
- WHEN its staleness is evaluated
- THEN it is treated as stale

#### Scenario: Missing surveillance data degrades rather than fails
- GIVEN the surveillance file cannot be read
- WHEN a screen runs
- THEN it completes with an empty list reported as stale

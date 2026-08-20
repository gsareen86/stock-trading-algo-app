# platform-api

## ADDED Requirements

### Requirement: Sector placement is readable
The API MUST expose the current sector placement with the measurements behind it.

#### Scenario: Placement returns measurements
- GIVEN a request for sector placement
- WHEN it is answered
- THEN each sector carries its quadrant, relative strength, change in relative strength, window
  and benchmark

#### Scenario: Unplaced sectors are reported
- GIVEN a sector with insufficient history
- WHEN placement is requested
- THEN it is present and marked unplaced with its reason

### Requirement: A scan can be started and its runs read
The API MUST expose starting a scan, listing past runs, and reading one run's results.

#### Scenario: A scan can be requested
- GIVEN an authenticated caller
- WHEN a scan is requested
- THEN a run identifier is returned

#### Scenario: Runs are listable newest first
- GIVEN several completed runs
- WHEN they are listed
- THEN they are returned newest first with their trigger, timestamp and outcome

#### Scenario: A run's results are paged and ordered
- GIVEN a completed run
- WHEN its results are requested
- THEN they are returned in ranking order, paged, with the ranking strategy named per entry

#### Scenario: Results can be filtered by stance agreement and by quality
- GIVEN a completed run
- WHEN results are requested filtered by a minimum count of BUY stances or a quality measure
- THEN only matching entries are returned
- AND the ordering rule is unchanged

#### Scenario: A run in progress is reported as such
- GIVEN a scan still running
- WHEN its run is requested
- THEN it is reported as in progress rather than as empty

#### Scenario: A second concurrent scan is refused
- GIVEN a scan already in progress
- WHEN another is requested
- THEN it is refused with the running run identified

### Requirement: A verdict's plan is served with the verdict
Where a strategy published a plan, the verdict endpoints MUST include it, with each level's
evidence reference.

#### Scenario: Plan travels with its verdict
- GIVEN a verdict carrying a plan
- WHEN the verdict is served
- THEN the plan is present with entry, stop, target, holding condition and evidence references

#### Scenario: A verdict without a plan omits the field
- GIVEN a verdict whose strategy published no plan
- WHEN it is served
- THEN no plan field is populated
- AND no default values are substituted

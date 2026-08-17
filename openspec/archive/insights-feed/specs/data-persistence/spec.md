# data-persistence

## ADDED Requirements

### Requirement: Insights carry a dedupe key and a stored severity
The insights table MUST hold a deduplication key and the severity of the insight's kind, both
indexed for suppression lookups.

#### Scenario: Suppression lookup is indexed
- GIVEN the insights table
- WHEN it is inspected
- THEN a dedupe key and creation time are indexed together

#### Scenario: Severity is stored rather than derived at read time
- GIVEN a recorded insight
- WHEN it is read
- THEN its severity is present on the row

# agent-graph

## ADDED Requirements

### Requirement: A cycle can assess risk against a book
The cycle MUST be able to produce a risk decision for each verdict against a named book's
positions, after the fan-in and without altering any verdict.

#### Scenario: Every verdict receives a decision
- GIVEN a cycle producing verdicts with risk assessment requested
- WHEN it completes
- THEN each verdict has a corresponding decision

#### Scenario: Risk runs after the fan-in
- GIVEN risk needs every verdict to judge portfolio impact
- WHEN the graph is built
- THEN risk is downstream of all strategy nodes

#### Scenario: Risk can be skipped
- GIVEN a cycle run without risk assessment
- WHEN it completes
- THEN verdicts are returned and no decisions are reported

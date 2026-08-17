# agent-graph

## ADDED Requirements

### Requirement: A cycle can surface insights
The cycle MUST be able to write insights after risk and narration, reading verdicts, risk
decisions, research findings, the regime and the book's positions.

#### Scenario: Insights run last
- GIVEN insights read narrated verdicts and risk decisions
- WHEN the graph is built
- THEN the insights node is downstream of both

#### Scenario: Cycle reports what was written
- GIVEN a cycle that surfaced insights
- WHEN it completes
- THEN the number written, suppressed and truncated is reported

#### Scenario: Surfacing can be skipped
- GIVEN a cycle run without insight surfacing
- WHEN it completes
- THEN no insight is written

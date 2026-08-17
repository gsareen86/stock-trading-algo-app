# agent-graph

## ADDED Requirements

### Requirement: A cycle screens when no symbols are supplied
The cycle MUST narrow the universe by screening when the caller names no instruments, and MUST
skip screening entirely when the caller names them.

#### Scenario: Screen narrows what the strategies evaluate
- GIVEN a cycle run with no symbols
- WHEN it completes
- THEN the strategies evaluated only the screened instruments
- AND the screen result is reported

#### Scenario: Explicit symbols bypass the screen
- GIVEN a cycle run naming an instrument that a screen would have excluded
- WHEN it completes
- THEN that instrument was still evaluated
- AND no screen was run

#### Scenario: Unavailable universe does not crash the cycle
- GIVEN the universe source fails
- WHEN a cycle runs
- THEN the cycle completes with no instruments and the failure recorded

# agent-graph

## ADDED Requirements

### Requirement: A cycle can report node completion to an observer
The graph MUST accept an optional observer that is notified as each node completes, and a
cycle's verdicts MUST be identical whether or not one is attached.

#### Scenario: Observed and unobserved cycles agree
- GIVEN the same instruments and the same price data
- WHEN a cycle is run with an observer and again without one
- THEN the verdicts are identical

#### Scenario: A failing observer never fails the cycle
- GIVEN an observer that raises when notified
- WHEN a node completes
- THEN the cycle continues and completes
- AND the failure is logged rather than propagated

#### Scenario: Parallel strategy nodes report independently
- GIVEN the four strategy nodes running in parallel
- WHEN each completes
- THEN each reports its own completion
- AND no node reports on behalf of another

#### Scenario: An observer cannot alter state
- GIVEN an observer attached to a cycle
- WHEN it is notified of a node's completion
- THEN it receives the node's identity and timing only
- AND nothing it does is written into cycle state

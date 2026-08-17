# llm-gateway

## ADDED Requirements

### Requirement: Local and hosted providers have separate timeouts
The gateway MUST apply a per-call timeout chosen by whether the dispatching rung is local, and
the local timeout MUST default to a value that allows a local model to complete a long
generation.

#### Scenario: Local rung waits longer
- GIVEN a task routed to a local provider
- WHEN the call is dispatched
- THEN the local timeout is applied

#### Scenario: Hosted rung keeps the shorter timeout
- GIVEN a task routed to a hosted provider
- WHEN the call is dispatched
- THEN the hosted timeout is applied

#### Scenario: Each rung in a chain gets its own
- GIVEN a hosted primary with a local fallback
- WHEN the primary fails and the fallback is tried
- THEN the hosted rung used the hosted timeout
- AND the local rung used the local timeout

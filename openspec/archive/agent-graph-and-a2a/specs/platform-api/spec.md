# platform-api

## ADDED Requirements

### Requirement: A cycle can be run on demand
`POST /cycles/run` MUST run the orchestrated cycle for named instruments and return one verdict
per strategy per instrument, with no combined stance anywhere in the response.

#### Scenario: Cycle returns one verdict per strategy
- GIVEN four registered strategies
- WHEN a cycle is run for one symbol
- THEN four verdicts are returned

#### Scenario: No combined stance appears
- GIVEN a cycle result
- WHEN the response is read
- THEN it carries no overall stance, score or consensus field

#### Scenario: Regime, research and notes are reported
- GIVEN a completed cycle
- WHEN the response is read
- THEN it reports the regime read, research findings and run notes

#### Scenario: Unreachable MCP server does not fail the request
- GIVEN a configured MCP server that cannot be reached
- WHEN a cycle is run
- THEN the response succeeds
- AND the server is reported as unreachable

#### Scenario: Agent graph unavailable
- GIVEN the agent dependencies are not installed
- WHEN a cycle is requested
- THEN the response reports the capability as unavailable rather than as a server error

### Requirement: The platform publishes an A2A agent card
`GET /.well-known/agent-card.json` MUST return an agent card listing the platform's registered
tools, rendered from the same manifests the tool definitions use.

#### Scenario: Card lists every registered tool
- GIVEN the tool registry
- WHEN the agent card is requested
- THEN every registered tool appears in it

#### Scenario: Card does not claim capabilities the platform lacks
- GIVEN the agent card
- WHEN its capabilities are read
- THEN streaming and push notifications are declared unsupported

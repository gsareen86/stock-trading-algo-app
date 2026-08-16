# tool-registry

Declared, schema-validated capabilities an agent can discover and call — each returning items already shaped as evidence.

Introduced by `skills-registry`, renamed to this capability by `tool-registry` (both in
`openspec/archive/`). The rename separates these — capabilities the *application* executes
under a schema — from Anthropic Agent Skills, which are procedural knowledge a *model* reads,
and from MCP tools, which an external server defines. See `openspec/project.md`.

### Requirement: A tool is declared by a manifest
Every tool MUST declare a name, version, summary, description, input JSON Schema, output
JSON Schema and a handler.

#### Scenario: Manifest exposes its contract
- GIVEN a registered tool
- WHEN its manifest is read
- THEN it carries a name, version, summary, description and both schemas

#### Scenario: Duplicate names rejected
- GIVEN two tools declaring the same name
- WHEN the registry loads them
- THEN the collision is reported rather than one silently overwriting the other

### Requirement: Tools are discovered by convention
The registry MUST discover tools from the tools package without an explicit registration
list.

#### Scenario: New tool directory is found
- GIVEN a new `app/tools/<name>/tool.py` exporting a manifest
- WHEN the registry loads
- THEN that tool is registered
- AND no other file was modified

#### Scenario: A tool that fails to import is reported
- GIVEN a tool module that raises on import
- WHEN the registry loads
- THEN the failure is recorded and retrievable
- AND the remaining tools still load

### Requirement: Input is validated before the handler runs
The registry MUST validate arguments against the tool's input schema and MUST NOT invoke the
handler when validation fails.

#### Scenario: Missing required argument
- GIVEN a tool requiring a `symbol` argument
- WHEN it is invoked without one
- THEN the result is not ok with reason `invalid_input`
- AND the handler was not called

#### Scenario: Wrong argument type
- GIVEN a tool whose `limit` argument is an integer
- WHEN it is invoked with a string
- THEN the result is not ok with reason `invalid_input`

#### Scenario: Valid input reaches the handler
- GIVEN arguments satisfying the input schema
- WHEN the tool is invoked
- THEN the handler receives them

### Requirement: Output is validated before it is returned
The registry MUST validate handler output against the tool's output schema, and MUST fail the
invocation when it does not conform.

#### Scenario: Handler returns a malformed shape
- GIVEN a handler returning output missing a required field
- WHEN the tool is invoked
- THEN the result is not ok with reason `invalid_output`
- AND the malformed data is not returned to the caller

#### Scenario: Conforming output returned
- GIVEN a handler returning output satisfying the schema
- WHEN the tool is invoked
- THEN the result is ok and carries that data

### Requirement: Every returned item carries a traceable source
Tool output items MUST include a `source_ref` and an `observed_at` timestamp.

#### Scenario: Item without a source is rejected
- GIVEN a handler returning an item with no `source_ref`
- WHEN the tool is invoked
- THEN the result is not ok with reason `invalid_output`

#### Scenario: Source reference survives to the caller
- GIVEN a tool returning an article
- WHEN the result is read
- THEN each item exposes the reference a reader can follow back to the source

### Requirement: A tool failure never raises into the caller
`invoke` MUST return a failed `SkillResult` rather than propagating an exception.

#### Scenario: Handler raises
- GIVEN a handler that raises
- WHEN the tool is invoked
- THEN the result is not ok with reason `handler_error`
- AND no exception escapes the registry

#### Scenario: Unknown tool requested
- GIVEN a name no tool declares
- WHEN it is invoked
- THEN the result is not ok with reason `unknown_skill`

#### Scenario: Failure reasons are distinguishable
- GIVEN invocations failing for different causes
- WHEN their reasons are compared
- THEN invalid input, invalid output, handler error and unknown tool are distinct

### Requirement: One manifest renders both bindings
Each manifest MUST render as an LLM tool definition and as an A2A card tool entry, from the
same declaration.

#### Scenario: Tool definition shape
- GIVEN a manifest
- WHEN a tool definition is rendered
- THEN it carries the tool's name, summary and input schema

#### Scenario: Agent card entry shape
- GIVEN a manifest
- WHEN an A2A tool entry is rendered
- THEN it carries the tool's id, name, description and tags

#### Scenario: Bindings need no agent framework installed
- GIVEN neither LangGraph nor an A2A SDK is installed
- WHEN either binding is rendered
- THEN it succeeds

### Requirement: Handlers receive their collaborators
The registry MUST pass a context carrying the platform's price source, calendar and clock,
and handlers MUST NOT construct their own.

#### Scenario: Injected price source used
- GIVEN a context built with a fake price source
- WHEN a price-dependent tool is invoked
- THEN it uses that source

#### Scenario: Tool modules import no provider directly
- GIVEN the tool modules
- WHEN their imports are inspected
- THEN none imports a network client at module scope

### Requirement: Tools gather rather than decide
Tools MUST return observations, and MUST NOT return scores, rankings or verdicts.

#### Scenario: News returns articles, not sentiment
- GIVEN the news research tool
- WHEN its output schema is inspected
- THEN it declares no sentiment, score or rating field

#### Scenario: Peer comparison returns measurements
- GIVEN the peer comparison tool
- WHEN it is invoked
- THEN it returns relative performance figures without declaring a winner

### Requirement: The seed tools are registered
The registry MUST provide `news_research`, `event_calendar`, `filings_scan` and
`peer_compare`.

#### Scenario: All four discoverable
- GIVEN the registry has loaded
- WHEN registered names are listed
- THEN all four are present with no load failures

### Requirement: Peer comparison works offline
`peer_compare` MUST compute relative performance from the injected price source, without
network access.

#### Scenario: Relative performance computed
- GIVEN a fake price source seeded for a subject and two peers
- WHEN peer comparison is invoked over a lookback window
- THEN each peer's return and the subject's relative performance are reported

#### Scenario: Peer with no data is reported, not dropped silently
- GIVEN a peer the price source has no data for
- WHEN peer comparison is invoked
- THEN that peer is reported as unavailable rather than omitted

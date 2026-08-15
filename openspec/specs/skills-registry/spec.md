# skills-registry

Declared, schema-validated capabilities an agent can discover and call — each returning items already shaped as evidence.

Introduced by `skills-registry` (see `openspec/archive/`).

### Requirement: A skill is declared by a manifest
Every skill MUST declare a name, version, summary, description, input JSON Schema, output
JSON Schema and a handler.

#### Scenario: Manifest exposes its contract
- GIVEN a registered skill
- WHEN its manifest is read
- THEN it carries a name, version, summary, description and both schemas

#### Scenario: Duplicate names rejected
- GIVEN two skills declaring the same name
- WHEN the registry loads them
- THEN the collision is reported rather than one silently overwriting the other

### Requirement: Skills are discovered by convention
The registry MUST discover skills from the skills package without an explicit registration
list.

#### Scenario: New skill directory is found
- GIVEN a new `app/skills/<name>/skill.py` exporting a manifest
- WHEN the registry loads
- THEN that skill is registered
- AND no other file was modified

#### Scenario: A skill that fails to import is reported
- GIVEN a skill module that raises on import
- WHEN the registry loads
- THEN the failure is recorded and retrievable
- AND the remaining skills still load

### Requirement: Input is validated before the handler runs
The registry MUST validate arguments against the skill's input schema and MUST NOT invoke the
handler when validation fails.

#### Scenario: Missing required argument
- GIVEN a skill requiring a `symbol` argument
- WHEN it is invoked without one
- THEN the result is not ok with reason `invalid_input`
- AND the handler was not called

#### Scenario: Wrong argument type
- GIVEN a skill whose `limit` argument is an integer
- WHEN it is invoked with a string
- THEN the result is not ok with reason `invalid_input`

#### Scenario: Valid input reaches the handler
- GIVEN arguments satisfying the input schema
- WHEN the skill is invoked
- THEN the handler receives them

### Requirement: Output is validated before it is returned
The registry MUST validate handler output against the skill's output schema, and MUST fail the
invocation when it does not conform.

#### Scenario: Handler returns a malformed shape
- GIVEN a handler returning output missing a required field
- WHEN the skill is invoked
- THEN the result is not ok with reason `invalid_output`
- AND the malformed data is not returned to the caller

#### Scenario: Conforming output returned
- GIVEN a handler returning output satisfying the schema
- WHEN the skill is invoked
- THEN the result is ok and carries that data

### Requirement: Every returned item carries a traceable source
Skill output items MUST include a `source_ref` and an `observed_at` timestamp.

#### Scenario: Item without a source is rejected
- GIVEN a handler returning an item with no `source_ref`
- WHEN the skill is invoked
- THEN the result is not ok with reason `invalid_output`

#### Scenario: Source reference survives to the caller
- GIVEN a skill returning an article
- WHEN the result is read
- THEN each item exposes the reference a reader can follow back to the source

### Requirement: A skill failure never raises into the caller
`invoke` MUST return a failed `SkillResult` rather than propagating an exception.

#### Scenario: Handler raises
- GIVEN a handler that raises
- WHEN the skill is invoked
- THEN the result is not ok with reason `handler_error`
- AND no exception escapes the registry

#### Scenario: Unknown skill requested
- GIVEN a name no skill declares
- WHEN it is invoked
- THEN the result is not ok with reason `unknown_skill`

#### Scenario: Failure reasons are distinguishable
- GIVEN invocations failing for different causes
- WHEN their reasons are compared
- THEN invalid input, invalid output, handler error and unknown skill are distinct

### Requirement: One manifest renders both bindings
Each manifest MUST render as an LLM tool definition and as an A2A card skill entry, from the
same declaration.

#### Scenario: Tool definition shape
- GIVEN a manifest
- WHEN a tool definition is rendered
- THEN it carries the skill's name, summary and input schema

#### Scenario: Agent card entry shape
- GIVEN a manifest
- WHEN an A2A skill entry is rendered
- THEN it carries the skill's id, name, description and tags

#### Scenario: Bindings need no agent framework installed
- GIVEN neither LangGraph nor an A2A SDK is installed
- WHEN either binding is rendered
- THEN it succeeds

### Requirement: Handlers receive their collaborators
The registry MUST pass a context carrying the platform's price source, calendar and clock,
and handlers MUST NOT construct their own.

#### Scenario: Injected price source used
- GIVEN a context built with a fake price source
- WHEN a price-dependent skill is invoked
- THEN it uses that source

#### Scenario: Skill modules import no provider directly
- GIVEN the skill modules
- WHEN their imports are inspected
- THEN none imports a network client at module scope

### Requirement: Skills gather rather than decide
Skills MUST return observations, and MUST NOT return scores, rankings or verdicts.

#### Scenario: News returns articles, not sentiment
- GIVEN the news research skill
- WHEN its output schema is inspected
- THEN it declares no sentiment, score or rating field

#### Scenario: Peer comparison returns measurements
- GIVEN the peer comparison skill
- WHEN it is invoked
- THEN it returns relative performance figures without declaring a winner

### Requirement: The seed skills are registered
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

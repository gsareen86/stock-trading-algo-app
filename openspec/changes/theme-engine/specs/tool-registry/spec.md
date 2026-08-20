# tool-registry

## ADDED Requirements

### Requirement: Policy and scheme announcements are retrievable as research
The system MUST provide a tool returning recent government policy and scheme announcements
relevant to industry, each with its publication date and a followable source reference.

#### Scenario: Announcements carry their date and source
- GIVEN retrieved policy announcements
- WHEN one is read
- THEN its publication date and source URL are present

#### Scenario: Nothing published is an empty result
- GIVEN a window with no relevant announcements
- WHEN policy is requested
- THEN the result is empty and says so
- AND no exception escapes the tool

#### Scenario: An unreachable source degrades rather than fails
- GIVEN the policy source cannot be reached
- WHEN policy is requested
- THEN the result is empty, the failure is reported, and the surrounding run completes

#### Scenario: Policy is never a measurement
- GIVEN a policy announcement supporting a theme
- WHEN a verdict is produced for a company in that theme
- THEN no evidence row cites the announcement

### Requirement: A theme chain is proposed through a declared tool contract
Chain expansion MUST be invoked through a tool with a declared input and output schema, and its
output MUST carry the model that produced it.

#### Scenario: Output is schema-validated before it is used
- GIVEN a model response that does not match the declared output schema
- WHEN the tool returns
- THEN the invocation is reported as an invalid output rather than passed on

#### Scenario: Every proposed tier carries its reasoning
- GIVEN a validated chain expansion
- WHEN a tier is read
- THEN the reasoning for it and the model that proposed it are present

#### Scenario: A failed expansion produces no chain
- GIVEN a model that is unavailable
- WHEN expansion is requested
- THEN no chain is produced and the failure is reported
- AND no partial chain is stored

#### Scenario: Expansion proposes inputs, never instruments
- GIVEN a validated chain expansion
- WHEN its tiers are read
- THEN they describe inputs and supplier categories
- AND resolving those to instruments happens outside this tool

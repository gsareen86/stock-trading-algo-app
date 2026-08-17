# agent-graph

The cycle: how the strategies are orchestrated, what the research step may do, and how external
tools reach the platform without weakening its contracts.

Introduced by `agent-graph-and-a2a` (see `openspec/archive/`).

### Requirement: Strategy nodes cannot observe one another
Strategy nodes MUST run without access to any other strategy's output. The state they are
handed MUST NOT contain a verdict produced by a sibling node in the same cycle.

#### Scenario: No strategy sees another's verdict
- GIVEN a cycle with more than one registered strategy
- WHEN the strategy nodes run
- THEN each observes no verdicts in its input state
- AND every strategy still contributes its own

#### Scenario: Fan-in is append-only
- GIVEN several strategy nodes completing
- WHEN their results are combined
- THEN each contributes without reading what the others contributed

#### Scenario: No function combines verdicts
- GIVEN the agent package
- WHEN it is searched for a function combining, merging, aggregating or blending verdicts
- THEN none exists

### Requirement: A cycle produces the same verdicts as direct evaluation
Running a strategy through the cycle MUST produce the same stance, conviction and evidence as
evaluating it directly. The orchestration MUST NOT change what a strategy decides.

#### Scenario: Cycle matches direct evaluation
- GIVEN the same instrument and price history
- WHEN a strategy is evaluated directly and through a cycle
- THEN the stance, conviction and evidence ids match

#### Scenario: Cycle completes with no language model available
- GIVEN no model answers any call
- WHEN a cycle runs
- THEN a verdict is produced for every registered strategy
- AND no exception reaches the caller

### Requirement: Research produces context, never evidence
The research step MUST NOT contribute to any verdict's evidence, gates or conviction.

#### Scenario: Findings never enter evidence
- GIVEN a cycle in which research gathered findings
- WHEN the verdicts are read
- THEN no evidence row originates from a research tool

#### Scenario: Research unavailable changes no verdict
- GIVEN research returns nothing
- WHEN a cycle runs
- THEN the verdicts are identical to a cycle where research was not requested

### Requirement: The tool-calling loop is bounded
The research step MUST stop after a configured number of tool-calling rounds.

#### Scenario: A model that never stops is stopped
- GIVEN a model that requests a tool on every round
- WHEN research runs with a bound of two rounds
- THEN exactly two rounds are issued

#### Scenario: Calling no tools is a valid answer
- GIVEN a model that requests no tools
- WHEN research runs
- THEN the step completes without error

### Requirement: The market regime is shared input, never a cycle-wide veto
A cycle MUST read the market regime once and expose it to every strategy as context. It MUST
NOT use the regime to override or veto any strategy's verdict.

#### Scenario: Regime is available to strategies
- GIVEN a cycle
- WHEN it runs
- THEN a regime read is recorded and reported

#### Scenario: Unavailable benchmark is unknown, not an error
- GIVEN the benchmark history cannot be fetched
- WHEN the regime is read
- THEN it is reported as unknown
- AND the cycle continues

### Requirement: External MCP tools are offered without being adopted
Tools from an external MCP server MUST be callable alongside local tools, MUST be namespaced by
their server, and MUST NOT be registered in the local tool registry.

#### Scenario: Remote tools are namespaced
- GIVEN a server named `kite` offering `get_ltp`
- WHEN its tools are offered to a model
- THEN the tool is named `kite:get_ltp`

#### Scenario: Remote tools stay out of the local registry
- GIVEN a discovered remote tool
- WHEN the local registry is inspected
- THEN that tool is absent from it

#### Scenario: Unreachable server degrades to local tools
- GIVEN a configured MCP server that cannot be reached
- WHEN a cycle runs
- THEN the server is reported unreachable
- AND local tools remain callable
- AND every strategy still produces a verdict

### Requirement: Mutating remote tools are refused
The platform MUST NOT offer a model any remote tool that places, modifies or cancels an order,
and MUST report which tools it refused.

#### Scenario: Order-placing tools are refused
- GIVEN a broker's server advertising `place_order` and `cancel_order`
- WHEN its tools are discovered
- THEN neither is offered to a model

#### Scenario: Read-only tools are offered
- GIVEN a server advertising `get_quotes` and `search_instruments`
- WHEN its tools are discovered
- THEN both are offered

#### Scenario: Refusals are visible
- GIVEN a server whose mutating tools were refused
- WHEN the cycle result is read
- THEN the refused tool names are reported

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

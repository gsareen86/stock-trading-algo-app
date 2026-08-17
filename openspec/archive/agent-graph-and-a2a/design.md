# Design: agent-graph-and-a2a

## 1. Why a graph library at all

The graph is `regime → research → (four strategies in parallel) → narrate → collect`. That is
perhaps twenty lines of `asyncio.gather`, and taking a dependency to avoid writing them would
be poor value. The dependency earns its place on one property instead.

**Isolation becomes structural.** Each strategy node declares the state keys it reads and
writes. It reads `instrument`, `regime` and `as_of`; it writes to `verdicts`, through a reducer
that appends. It has no access to another strategy's output because the graph does not give it
one — not because the code politely refrains. That is the same move as `Verdict.__post_init__`
forcing `AVOID` on a failed gate: the rule this platform exists to protect is enforced by a
type or a topology rather than by reviewer attention.

With `asyncio.gather`, isolation lasts exactly until someone writes a node that reads
`results[0]` for context. That is precisely how the predecessor's confluence scorecard began —
not as a decision, but as a convenience.

What we deliberately do not adopt: checkpointers, interrupts, human-in-the-loop, subgraph
composition. The graph is a topology and a state contract; everything else stays out until
something needs it.

## 2. State, and the reducer that keeps verdicts apart

```python
class CycleState(TypedDict):
    cycle_id: str
    as_of: datetime
    instruments: list[Instrument]     # inputs, read-only after regime
    regime: RegimeRead | None         # written by regime, read by all
    research: dict[str, list[dict]]   # ticker -> evidence-shaped findings
    verdicts: Annotated[list[Verdict], operator.add]   # append-only fan-in
    notes: Annotated[list[str], operator.add]
```

`verdicts` uses an additive reducer, so four parallel nodes each contribute without any of them
reading what the others wrote. The reducer is the whole isolation guarantee, so it is asserted
directly: a test drives two strategy nodes concurrently and checks that neither observed the
other's verdict in its input state.

`research` is keyed by ticker and read by strategies as *context*, never as evidence. Anything a
strategy asserts must still come from its own deterministic measurement — research can tell a
narrative that earnings are due on Thursday; it cannot become a gate.

## 3. The research node is the first place a model chooses anything

`research` runs a bounded tool-calling loop: the model sees every tool's `summary` (the
selection signal `tool-registry` sharpened), picks tools, and receives their validated output.

Three constraints make this safe rather than exciting:

- **Arguments are validated by the manifest's schema before any handler runs.** The registry
  already does this — `invoke` refuses an invalid payload rather than passing it on. A model
  producing malformed arguments gets a typed failure, not a stack trace.
- **The loop is bounded** by a maximum number of rounds. An agent that keeps calling tools
  until it feels finished is an agent that occasionally never finishes.
- **Its output is context, not evidence.** Nothing research returns can pass a gate or move a
  conviction. If the model calls no tools, or every call fails, the strategies run exactly as
  they do today — which is what keeps "reproducible with the LLM off" literally true.

## 4. MCP tools sit beside local tools, and are not pretended to be them

An MCP server's tools are discovered at connect time and exposed to the model alongside the
local registry, under a namespaced name (`kite:search_instruments`) so the origin of a tool is
never ambiguous in a trace.

They are **not** registered in `ToolRegistry`. That registry's contract is that every tool
declares an output schema and returns evidence-shaped items with a `source_ref` — guarantees we
make about our own code and cannot make about someone else's server. Merging them would either
weaken the contract to whatever MCP offers or lie about what an MCP tool returns. Two sets,
one prompt, honest about which is which.

Connection failure is a normal outcome: the toolbelt reports the server as unavailable and the
cycle proceeds with local tools only. A research step is an enhancement; a broker's MCP server
being down must not stop four strategies from evaluating a stock.

## 5. The A2A card is a document, not a server

`GET /.well-known/agent-card.json` renders the card from the same manifests that produce tool
definitions, via `to_a2a_skill`. That is the whole of A2A in this increment.

A full A2A task server — endpoints, task lifecycle, streaming — has no caller. This repo has
already paid once for building a binding ahead of its consumer, and `to_a2a_skill` was the
binding in question. Publishing the card makes the platform discoverable and exercises the
renderer against a real HTTP response; the protocol server waits for an agent that wants to
talk to it.

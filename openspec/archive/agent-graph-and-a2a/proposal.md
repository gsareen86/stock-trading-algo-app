# agent-graph-and-a2a

## Intent

Make the four strategies run as one orchestrated, traceable cycle rather than a loop inside an
API handler — and open the tool surface to external MCP servers.

## Why

`POST /verdicts/evaluate` works, and it is a `for` loop. That is fine for evaluating a symbol
on demand and wrong as the shape of the platform, for three reasons that only get more
expensive later:

- **Strategy isolation is currently a convention.** The loop happens to call each strategy with
  its own context; nothing stops a future edit from passing one strategy's result into another,
  which is how the predecessor's confluence scorecard grew. Isolation should be enforced by the
  structure that runs them.
- **There is no research step.** Four tools exist (`news_research`, `filings_scan`,
  `event_calendar`, `peer_compare`) and nothing calls them. `to_tool_definition` has never been
  used — its correctness is currently a claim, not an observation.
- **Nothing external can reach any of this.** The A2A card exists as a renderer with no server.

## In scope

- **`CycleState` and a LangGraph `StateGraph`** — the run's shape as data
- **Nodes that can exist today**: `regime`, `research`, the four strategies fanned out in
  parallel, `narrate`, `collect`
- **Real tool-calling in `research`** — the model chooses tools from the registry, arguments
  are validated by the manifest's own schema before any handler runs
- **An MCP client** — external servers' tools joining the callable set, Zerodha Kite first
- **`GET /.well-known/agent-card.json`** — the A2A card, `to_a2a_skill`'s first real consumer
- **`POST /cycles/run`**

## Out of scope — and why these specifically

The cycle in `project.md` has three more nodes. Each is blocked on an increment that has not
happened, and building a placeholder for any of them would be inventing behaviour to be
replaced:

- **`screen`** needs the investable universe and hard gates — `screening-universe-and-gates`
- **`risk`** needs positions and a ledger to size against — `books-ledger-and-analytics`
- **`insights`** needs somewhere for insights to go — `insights-feed`

Also out:

- **Checkpointing and resume.** LangGraph offers it; nothing here runs long enough to need it,
  and a persistence layer for graph state is a schema decision that should wait for a reason.
- **Serving A2A over HTTP as a task protocol.** The card is the seam worth having now; a full
  A2A server with no external agent calling it is the mistake this repo already made once.

## Risks

- **LangGraph is a real dependency with a real mental model.** Justified in `design.md` §1 by
  one property — enforced state isolation — rather than by convention. If that argument does
  not hold, neither does the dependency.
- **MCP tools are defined by someone else.** Their schemas are not ours to validate against,
  and a remote server can change under us. Kept behind the same failure contract as everything
  else: unavailable is a normal outcome, never an exception.
- **Tool-calling puts a model in the loop of a cycle.** It selects *what to look up*; it still
  decides nothing. Verdicts remain deterministic and reproducible with the LLM off.

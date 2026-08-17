# Tasks: agent-graph-and-a2a

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: agent-graph (new), tool-registry (ADDED), platform-api (ADDED)

## Dependencies
- [x] `langgraph`, `mcp` as an `agents` extra, imported lazily

## State and graph
- [x] `app/agents/state.py` — `CycleState`, additive reducer for verdicts
- [x] `app/agents/graph.py` — regime → research → 4 strategies → narrate → collect
- [x] Strategy nodes read shared inputs only; never another strategy's output

## Nodes
- [x] `regime` — weekly index read, shared context
- [x] `research` — bounded tool-calling loop over the toolbelt
- [x] `strategy.<id>` — one per registered strategy, fanned out
- [x] `narrate` — reuses `verdict-narratives`
- [x] `collect` — terminal assembly

## Toolbelt
- [x] `app/agents/toolbelt.py` — local manifests plus MCP tools, namespaced
- [x] `app/agents/mcp_client.py` — connect, list tools, call; failure is a normal outcome
- [x] MCP tools are not registered in `ToolRegistry`

## API
- [x] `POST /cycles/run`
- [x] `GET /.well-known/agent-card.json`

## Tests
- [x] Parallel strategy nodes cannot observe each other's verdicts
- [x] A cycle with the LLM unavailable still produces all four verdicts
- [x] Research output never becomes evidence or changes a stance
- [x] Tool-call loop is bounded
- [x] Invalid tool arguments are refused by the manifest schema, not the handler
- [x] MCP server unreachable degrades to local tools
- [x] Agent card lists every registered tool

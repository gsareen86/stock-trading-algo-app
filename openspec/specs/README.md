# Specs

The source of truth for **current** system behavior, one directory per capability.

Populated by archiving changes — a spec here should never be hand-edited to describe
behavior that hasn't shipped. If you need to change what the system does, that goes through
`openspec/changes/` first (see `openspec/AGENTS.md`).

| Capability | Covers |
|---|---|
| `platform-configuration` | Settings precedence, validation, per-task LLM routing |
| `data-persistence` | Migration ownership, the `trading` namespace, RLS, the cleanup guard |
| `llm-gateway` | Task-named routing, fallback chains, failing soft, budget cap, tracing |
| `llm-observability` | The local call ledger — cost, tokens, failure modes, IST-day rollup |
| `platform-api` | `GET /health`, `GET /llm/usage`, `GET /llm/calls` |
| `web-shell` | The six surfaces, design tokens, the backend seam, the Engine LLM panel |

These carry full Requirement+Scenario depth because they describe code that was just written;
later capabilities may enter at `Status: baseline` depth and be promoted the first time a real
change touches them.

Shipped so far: `bootstrap-platform-skeleton`, `llm-gateway-and-observability`.

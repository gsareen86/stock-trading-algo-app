# Specs

The source of truth for **current** system behavior, one directory per capability.

Populated by archiving changes — a spec here should never be hand-edited to describe
behavior that hasn't shipped. If you need to change what the system does, that goes through
`openspec/changes/` first (see `openspec/AGENTS.md`).

| Capability | Covers |
|---|---|
| `platform-configuration` | Settings precedence, validation, per-task LLM routing |
| `data-persistence` | Migration ownership, the `trading` namespace, RLS, the cleanup guard |
| `llm-gateway` | Task-named routing across seven providers, failing soft, tracing |
| `platform-api` | `GET /health` — the seam report |
| `web-shell` | The six surfaces, design tokens, the backend seam |

All five arrived with `bootstrap-platform-skeleton`. They carry full Requirement+Scenario
depth because they describe code that was just written; later capabilities may enter at
`Status: baseline` depth and be promoted the first time a real change touches them.

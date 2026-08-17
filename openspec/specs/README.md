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
| `market-data` | Price history, universe, quarterly fundamentals and sector indices |
| `market-calendar` | NSE trading days and session hours, with staleness made visible |
| `decision-model` | Verdicts, evidence and gates — independence and traceability enforced |
| `strategies` | Strategy discovery and all four implementations, each with its own conviction |
| `tool-registry` | Declared, schema-validated capabilities returning evidence-shaped items |
| `verdict-narratives` | Generated prose, and the guard that keeps every figure in it traceable |
| `screening` | Eligibility filters, turnover floors, surveillance and traceable exclusions |
| `agent-graph` | The cycle, research bounds, MCP tools and the read-only rule |
| `books-ledger` | One ledger parameterised by book, the execution boundary, gross analytics |
| `risk-management` | Portfolio gates and sizing — vetoes acting, never alters a verdict |
| `insights-feed` | What reaches the reader: portfolio consequences, deduped, in-app only |
| `portfolio-health` | Structural scoring of the book, and deterministic next steps |
| `platform-api` | `/health`, `/llm/usage`, `/llm/calls`, `/tools`, `/strategies`, `/verdicts`, `/cycles/run`, `/screen`, `/universe`, `/books/{book}/*`, `/insights`, `/insights/{id}/act` |
| `web-shell` | The six surfaces, design tokens, the backend seam, the Engine LLM panel |

These carry full Requirement+Scenario depth because they describe code that was just written;
later capabilities may enter at `Status: baseline` depth and be promoted the first time a real
change touches them.

Shipped so far: `bootstrap-platform-skeleton`, `llm-gateway-and-observability`,
`market-data-foundation`, `skills-registry`, `verdict-model-and-minervini`,
`remaining-three-strategies`, `inr-cost-reporting`, `tool-registry`, `verdict-narratives`, `local-run-ergonomics`, `agent-graph-and-a2a`, `screening-universe-and-gates`, `books-ledger-and-analytics`, `insights-feed`, `portfolio-health-and-actions`.

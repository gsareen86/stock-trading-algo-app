# bootstrap-platform-skeleton

## Intent

Stand up a walking skeleton of the rebuilt platform — thin, but touching every
architecturally risky seam end-to-end so none of them stays unproven.

## Why

The predecessor's problems were structural, not local: config that could be set three ways,
a hand-rolled schema with no migration path, an LLM client wired directly into feature code,
and no tests. Those seams are exactly the ones that are expensive to change later, so this
change proves all of them at once while there is almost no code to rework — a FastAPI app
that reads typed settings, migrates a real Supabase schema, makes one traced LLM call
through the gateway, and serves a Next.js shell that consumes it.

Nothing here makes a trading decision. That is deliberate: the decision model (verdicts,
evidence, strategies, agents) lands in later changes, on top of seams that already work.

## In scope

- `openspec/` scaffold for the rebuilt app, and this change
- `backend/` — FastAPI app, typed `pydantic-settings` with a stated precedence chain,
  structured logging, IST clock
- `backend/persistence/` — SQLAlchemy models and the first Alembic migration, applied to
  both SQLite and the Supabase Postgres project
- Creating `insights` and `verdicts` in a dedicated `trading` schema, **with RLS enabled
  and policies in the same migration**, leaving the predecessor's `public` tables untouched
- `backend/app/llm/` — LiteLLM-backed gateway behind a narrow internal interface, with
  circuit breaker, disk cache, config-driven routing for 7 providers, Langfuse wiring
- `GET /health` reporting app, database and LLM-provider status
- `backend/tests/` — a real pytest suite
- `web/` — Next.js 15 shell with design tokens and the 6-surface navigation, dashboard
  making one live call to the backend

## Out of scope

Explicitly deferred, each to its own change:

- Strategies, `Verdict`/`Evidence` models, narratives *(changes 5–7)*
- LangGraph cycle and A2A adapters *(change 8)*
- Skills registry *(change 4)*
- Market-data plumbing port *(change 3)*
- Books, ledger, backtesting *(changes 10, 12)*
- Real GUI content — the 6 routes render labelled placeholders *(changes 13+)*
- Deleting the legacy root packages — tracked separately, after the data port

## Risks

- **Langfuse and most LLM providers need credentials that may be absent.** The gateway must
  degrade to a clearly-reported unconfigured state, never crash the app, and `/health` must
  say which providers are actually reachable.
- **The legacy tables stay exposed.** All 30 remain in `public` with RLS disabled, which the
  Supabase security advisor reports as 30 ERRORs. This change deliberately does not touch
  them; securing them is tracked separately.

## Correction: the legacy tables were not empty

This change was proposed on the basis that all 30 legacy tables held 0 rows, and originally
planned to drop them. That was wrong. `list_tables` reports *estimated* row counts from
Postgres statistics; an exact `COUNT(*)` found roughly **47,500 rows**, including 472 trades,
206 positions, 325 signal outcomes and ~20,000 signals — history that `backtesting` and
`books-ledger-and-analytics` will want.

The scope changed in response: the rebuild takes its own `trading` schema and nothing is
dropped. The emptiness guard survives, unwired, for the future cleanup milestone.

Two things worth carrying forward: estimated row counts are not evidence for a destructive
decision, and the assert-empty guard would have refused this drop even if it had been
attempted.

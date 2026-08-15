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
- Dropping the 30 empty legacy tables and creating `insights` and `verdicts` **with RLS
  enabled and policies in the same migration**
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

- **Supabase migration is destructive.** It drops 30 tables. All are verified empty (0 rows)
  and the drop is confined to that explicit list; the migration fails rather than proceeds
  if an unexpected table is present.
- **Langfuse and most LLM providers need credentials that may be absent.** The gateway must
  degrade to a clearly-reported unconfigured state, never crash the app, and `/health` must
  say which providers are actually reachable.

# Tasks: bootstrap-platform-skeleton

## Spec
- [x] `openspec/` scaffold — `project.md`, `AGENTS.md`, `specs/`, `changes/`, `archive/`
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Delta specs: platform-configuration, data-persistence, llm-gateway, platform-api,
      web-shell

## Backend — core
- [x] `backend/pyproject.toml` — deps, ruff + pytest config
- [x] `app/core/settings.py` — typed `Settings`, precedence chain, `__`-nested LLM routes
- [x] `app/core/logging.py` — structured logging
- [x] `app/core/clock.py` — IST clock; UTC storage, IST display

## Backend — persistence
- [x] `app/persistence/base.py`, `models.py` — `insights`, `verdicts` in the `trading` schema
- [x] Alembic env wired to `Settings`; schema created before Alembic's version table
- [x] First revision: create `trading` schema → tables → RLS + `service_role` policies
- [x] `app/persistence/legacy.py` — legacy inventory + emptiness guard for the future
      cleanup milestone (deliberately unwired)

## Backend — LLM gateway
- [x] `app/llm/types.py` — `Message`, `LLMResult`, `LLMGateway` Protocol
- [x] `app/llm/gateway.py` — LiteLLM Router, task→model routing, returns `None` on failure
- [x] `app/llm/breaker.py`, `app/llm/cache.py` — circuit breaker, content-hash disk cache
- [x] `app/llm/observability.py` — Langfuse callback, no-op when unconfigured
- [x] `app/llm/providers.py` — 7-provider config incl. OpenAI-compatible local three

## Backend — API
- [x] `app/api/health.py` — `GET /health`: app, DB + alembic revision, per-provider status
- [x] `app/main.py` — app factory, CORS for the web origin

## Backend — tests
- [x] Settings precedence, incl. `__`-nested route override
- [x] `/health` shape and degraded states
- [x] Migration creates expected tables on clean SQLite
- [x] Gateway: task routing, `None` on provider failure, breaker opens, cache hit
- [x] Migration is non-destructive; populated legacy tables survive
- [x] Cleanup guard aborts when a legacy table is non-empty

## Supabase
- [x] Exact `COUNT(*)` on all 30 legacy tables — found ~47.5k rows, **not** empty
- [x] Apply migration (non-destructive: creates `trading` schema only)
- [x] Verify `trading.verdicts` / `trading.insights` exist with RLS + `service_role` policies
- [x] Verify legacy `public` row counts unchanged
- [x] `get_advisors` — no advisory names a `trading` table; 30 pre-existing legacy ERRORs
      remain, deliberately untouched

## Web
- [ ] `npx create-next-app` — TS, Tailwind, App Router
- [ ] Design tokens + shadcn/ui base
- [ ] Nav shell: Today, Ideas, Positions, Stock, Performance, Engine (placeholders)
- [ ] Dashboard fetches backend `/health` and renders seam status

## Verify & ship
- [ ] `pytest`, `ruff check`, `alembic upgrade head` on clean SQLite
- [ ] `npm run build`, `npm run lint`
- [ ] All 6 routes render; dashboard shows live backend data
- [ ] Archive delta into `openspec/specs/`, move change to `openspec/archive/`
- [ ] Commit, `git push -u origin claude/swing-lt-platform-v2`

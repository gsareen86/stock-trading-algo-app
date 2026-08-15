# Tasks: bootstrap-platform-skeleton

## Spec
- [x] `openspec/` scaffold — `project.md`, `AGENTS.md`, `specs/`, `changes/`, `archive/`
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Delta specs: platform-configuration, data-persistence, llm-gateway, platform-api,
      web-shell

## Backend — core
- [ ] `backend/pyproject.toml` — deps, ruff + pytest config
- [ ] `app/core/settings.py` — typed `Settings`, precedence chain, `__`-nested LLM routes
- [ ] `app/core/logging.py` — structured logging
- [ ] `app/core/clock.py` — IST clock; UTC storage, IST display

## Backend — persistence
- [ ] `app/persistence/base.py`, `models.py` — `insights`, `verdicts`
- [ ] Alembic env wired to `Settings`, SQLite + Postgres
- [ ] First revision: assert-empty → drop 30 legacy tables → create new → enable RLS +
      `service_role` policies

## Backend — LLM gateway
- [ ] `app/llm/types.py` — `Message`, `LLMResult`, `LLMGateway` Protocol
- [ ] `app/llm/gateway.py` — LiteLLM Router, task→model routing, returns `None` on failure
- [ ] `app/llm/breaker.py`, `app/llm/cache.py` — circuit breaker, content-hash disk cache
- [ ] `app/llm/observability.py` — Langfuse callback, no-op when unconfigured
- [ ] `app/llm/providers.py` — 7-provider config incl. OpenAI-compatible local three

## Backend — API
- [ ] `app/api/health.py` — `GET /health`: app, DB + alembic revision, per-provider status
- [ ] `app/main.py` — app factory, CORS for the web origin

## Backend — tests
- [ ] Settings precedence, incl. `__`-nested route override
- [ ] `/health` shape and degraded states
- [ ] Migration creates expected tables on clean SQLite
- [ ] Gateway: task routing, `None` on provider failure, breaker opens, cache hit
- [ ] Legacy-drop guard aborts when a table is non-empty

## Supabase
- [ ] Confirm all 30 legacy tables still empty
- [ ] Apply migration
- [ ] `list_tables` — legacy gone, new present
- [ ] `get_advisors` — no `rls_disabled` critical for new tables

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

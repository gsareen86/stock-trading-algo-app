# Tasks: llm-gateway-and-observability

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: llm-gateway (MODIFIED + ADDED), llm-observability (new), platform-api,
      web-shell (MODIFIED)

## Settings
- [x] `llm_fallback: dict[str, str]` — comma-separated chain per task
- [x] `llm_daily_budget_usd: float | None` — unset means unlimited
- [x] `chain_for_task(task)` — ordered list of targets, primary first

## Gateway
- [x] `app/llm/routing.py` — build Router `model_list` + `fallbacks` from settings
- [x] Breaker prunes the chain instead of vetoing the call
- [x] Dispatch through `Router.acompletion`
- [x] `LLMResult.requested_model` / `used_fallback`; `model` = the model that answered
- [x] `app/llm/budget.py` — cached daily total, paid-vs-local classification

## Persistence
- [x] `LlmCall` model + `0002` migration (RLS + policy, `trading` schema)
- [x] `app/llm/recorder.py` — write one row per attempt, swallow its own failures
- [x] Aggregation query grouped by IST day / task / provider

## API
- [x] `GET /llm/usage` — totals, per-task, per-provider, budget
- [x] `GET /llm/calls` — recent, bounded, no prompt content

## Web
- [x] Engine surface renders spend, tokens, budget and recent calls
- [x] Empty state and backend-unreachable state

## Tests
- [x] Chain resolution and order
- [x] Fallback serves when primary fails; result names the serving model
- [x] Breaker prunes rather than vetoes; all-open returns None
- [x] Budget blocks paid, exempts local, unset means unlimited
- [x] Recorder writes every status; logging failure does not break the call
- [x] Cost null for local; aggregate separates priced/unpriced
- [x] IST day boundary attribution
- [x] `/llm/usage` and `/llm/calls` shapes, bounds, no leakage

## Verify & ship
- [x] `pytest`, `ruff`; `alembic upgrade head` clean; `0002` applied to Supabase
- [x] `npm run build`, `npm run lint`; Engine renders live
- [x] Archive deltas into `openspec/specs/`, move change to `openspec/archive/`
- [x] Commit, push

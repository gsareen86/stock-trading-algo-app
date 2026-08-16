# Tasks: inr-cost-reporting

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: platform-configuration (ADDED + MODIFIED), llm-gateway (MODIFIED),
      platform-api (MODIFIED), web-shell (MODIFIED)

## Settings
- [x] `usd_inr_rate: float` (gt=0), default 88.0
- [x] `llm_daily_budget_inr` replaces `llm_daily_budget_usd`
- [x] Reject the retired `LLM_DAILY_BUDGET_USD` key at startup, naming the replacement
- [x] `daily_budget_usd` derived property — the cap in ledger currency

## Money
- [x] `app/core/money.py` — `usd_to_inr` / `inr_to_usd` / `round_inr`, one place, documented

## Budget
- [x] `DailyBudget` constructed from the derived USD cap; internals unchanged

## API
- [x] `/llm/usage` reports `spend_inr`, budget in INR, and `usd_inr_rate`
- [x] `/llm/calls` reports `cost_inr` alongside the stored `cost_usd`

## Web
- [x] `money()` renders `₹`, two decimals, `< ₹0.01` below a paisa
- [x] Types renamed; budget bar names `LLM_DAILY_BUDGET_INR`
- [x] Panel shows the rate in use

## Tests
- [x] Conversion round-trips and rejects a non-positive rate
- [x] Retired budget key fails startup with a message naming the new one
- [x] `/llm/usage` reports INR consistent with the returned rate
- [x] Cap in INR enforces at the equivalent USD spend

# llm-gateway-and-observability

## Intent

Make the LLM gateway survivable and accountable: a provider going down should reroute rather
than degrade the platform, and every rupee and token spent should be visible in the app
without a Langfuse account.

## Why

`bootstrap-platform-skeleton` proved the gateway seam but left it thin in two ways that
matter once real work runs through it.

**Survivability.** A task resolves to exactly one model. If that provider is down, rate-limited
or unconfigured, the call returns `None` and the caller falls back to its non-LLM path — which
for narrative generation means no explanation at all. With seven providers configured, a
frontier model being unavailable should mean *reroute to the local one*, not *give up*.

**Accountability.** Cost and usage exist only inside Langfuse. That is the wrong place for
them to live exclusively: Langfuse is optional, external, and unconfigured in most local
setups, and the predecessor's one genuinely useful observability feature was a `llm_call_log`
table the dashboard could read. Without a local record there is no way to answer "what did
today cost?" offline, and no way to stop it running away.

## In scope

- **Per-task fallback chains**, configured as `LLM_FALLBACK__<TASK>` and walked one rung at a
  time. (`litellm.Router` is deliberately *not* used — its failover is opaque from outside,
  and this change needs every attempt individually recorded. See `design.md` §1.)
- Circuit breaker reworked to cooperate with fallbacks — a provider whose breaker is open is
  skipped, and the chain continues rather than the call failing
- **`trading.llm_calls`** — one row per call attempt regardless of outcome, recording task,
  provider, model, tokens, cost, latency, status and trace id
- **Daily budget guardrail** — a configurable USD cap; once reached, paid calls stop and are
  recorded as `budget_exceeded`. Local models never count against it
- **`GET /llm/usage` and `GET /llm/calls`** — spend and recent activity for the app to render
- The **Engine surface** wired to those endpoints, so cost, failures and fallback behaviour
  are visible in-app

## Out of scope

- Streaming responses — nothing in the roadmap needs token-by-token output
- Prompt registry / versioning in Langfuse — belongs with `verdict-narratives`, which is the
  first change that actually has a prompt worth versioning
- Semantic caching — the content-hash cache is sufficient until there are real prompts to
  measure against
- The rest of the Engine surface (config, run history, agent traces, backtest lab) —
  this change adds only the LLM panel

## Scope calls worth flagging

Two things here go slightly beyond a literal reading of "LiteLLM router, all 7 providers,
Langfuse", and are included deliberately:

- **The budget cap.** Observability that only watches money leave is half a feature, and a
  runaway agent loop against a frontier model is a real failure mode for this app.
- **The Engine LLM panel.** Backend-only observability would leave this increment unverifiable
  by you without a Langfuse account. It is one panel, not the whole surface.

Say the word if either should come out.

## Risks

- **Fallbacks can silently change which model answered.** Every result must report the model
  that actually served it, not the one that was requested, or traceability breaks.
- **Cost figures for local models are not zero-cost to get wrong.** LiteLLM reports no cost
  for local providers; recording `0.0` rather than `NULL` would understate nothing but
  overstate confidence. Unknown stays unknown.

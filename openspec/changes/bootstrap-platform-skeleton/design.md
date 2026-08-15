# Design: bootstrap-platform-skeleton

Only the decisions that aren't obvious from the proposal.

## 1. Configuration precedence

The predecessor's worst tracking pain was a setting that could come from code, `.env`, or a
live DB row with no stated winner. There is now exactly one chain, highest priority first:

1. Explicit constructor arguments — used by tests only
2. Process environment variables
3. `.env` file
4. Field defaults declared in `backend/app/core/settings.py`

**No runtime-mutable config.** Nothing reads settings from the database. If a value needs to
change at runtime it becomes an explicit domain concept with its own table and its own spec,
not a config knob.

Nested settings use pydantic-settings' `__` delimiter, which is what makes per-task LLM
routing declarative: `LLM_ROUTE__NARRATIVE=ollama/llama3.1` overrides one route without
touching the others.

`Settings` is constructed once and injected via a FastAPI dependency, never imported as a
module-level singleton — that's what makes the precedence chain testable at all.

## 2. Why LiteLLM sits behind a narrow interface

LiteLLM is the routing core, but feature code never imports it. Everything goes through:

```python
class LLMGateway(Protocol):
    async def complete(self, *, task: str, messages: list[Message],
                       schema: dict | None = None) -> LLMResult | None: ...
```

Three reasons this indirection earns its place:

- **`task`, not `model`.** Callers name the job (`"narrative"`, `"research"`); the mapping to
  a provider/model is config. This is what allows narratives to run locally while research
  runs on a frontier model, with no code change.
- **Returns `None`, never raises.** Carried over from the legacy `llm/client.py`, whose one
  genuinely good rule was that a trading cycle must never crash because a provider is down or
  rate-limited. Callers always have a non-LLM path.
- **It keeps LiteLLM swappable.** A gateway that leaks `litellm` types into strategy code
  would make replacing it a rewrite.

The **circuit breaker** and **disk cache** also carry over: after N consecutive rate-limit
failures the breaker opens and calls short-circuit to `None` for a cooldown, and prompts that
are stable by construction are cached by content hash so repeated identical calls never hit
the network.

Provider routing — the local three are OpenAI-compatible, so they need no adapter code:

| Provider | Route |
|---|---|
| Anthropic, Gemini, OpenAI | native LiteLLM provider prefixes |
| Ollama, LM Studio | `ollama/`, `lm_studio/` |
| llama.cpp, AMD Lemonade | `openai/<model>` + `api_base` |

## 3. Langfuse attaches at the gateway, not at call sites

Langfuse is registered as a LiteLLM callback inside the gateway, so every call is traced
without any feature module knowing observability exists. `LLMResult` carries the `trace_id`
back out, which is what later lets a `Verdict` link its narrative to the exact trace that
produced it. With no Langfuse credentials configured the callback is simply not registered —
tracing degrades to off, calls still work.

## 4. The destructive migration

The first Alembic revision drops the 30 legacy tables. Two safeguards, because this is the
one irreversible step in the change:

- The drop list is **explicit and hard-coded** — not `DROP SCHEMA` or a reflection-driven
  loop. A table that isn't on the list is never touched.
- The migration **asserts each table is empty before dropping it** and aborts the whole
  transaction otherwise. All 30 were verified at 0 rows when this was written; the assertion
  is there for the case where that stops being true before it runs.

`downgrade()` recreates the new tables but deliberately **cannot** restore the legacy ones —
they carry no data worth reconstructing, and a downgrade that fabricated 30 empty tables
would imply a rollback path that doesn't really exist.

## 5. RLS posture

The legacy schema had RLS disabled on all 30 tables, meaning anyone with the anon key could
read or write every row. The new posture:

- RLS **enabled** on every table, in the same migration that creates it
- An explicit `service_role` full-access policy per table — technically redundant, since
  `service_role` bypasses RLS, but it documents intent in the schema itself and keeps the
  "RLS enabled, zero policies" lint from looking like an oversight
- **No policy for `anon` or `authenticated`.** Under Postgres RLS, absence of a permissive
  policy is a deny. The browser is not a database client here; it talks to FastAPI, which
  holds the service-role credential server-side.

This is why the migration can enable RLS safely where the bare `ENABLE` the advisory
suggested would have locked the app out — the backend was never relying on the anon role.

## 6. What `/health` is for

Not a liveness probe. It's the seam report: app version, database connectivity and current
Alembic revision, and per-provider LLM configuration status. Wiring problems in a
multi-provider, multi-service stack are otherwise invisible until a feature fails, and this
is the one endpoint the web shell consumes in this change — so a broken seam shows up in the
UI immediately rather than in a log nobody reads.

Provider status distinguishes **configured** (credentials present) from **reachable**
(responded to a probe), because "the key is set" and "the server is up" fail differently and
a local Ollama being down is not the same problem as an absent Anthropic key.

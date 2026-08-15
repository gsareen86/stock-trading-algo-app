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

## 4. Namespacing instead of a destructive migration

The rebuild creates a `trading` schema and puts its tables there. The predecessor's 30 tables
stay in `public`, untouched.

This replaces an earlier plan to drop them. That plan rested on all 30 being empty, which
came from `list_tables`' *estimated* row counts; an exact `COUNT(*)` found ~47,500 rows,
including 472 trades and 206 positions. Estimates are not evidence for a destructive
decision — that is the lesson worth keeping, more than the schema choice itself.

Namespacing turns out to be better on the merits anyway:

- Nothing is destroyed, so `backtesting` and `books-ledger-and-analytics` can still read real
  history rather than starting from an empty ledger.
- "Is this the new app or the old one?" is answerable from the table name alone — the same
  clarity the drop was meant to buy.
- A non-`public` schema is not exposed by PostgREST unless someone opts it in, so the new
  tables are unreachable over the REST API by construction.

SQLite has no schemas. Rather than keep two model definitions, the `trading` namespace is
translated away for SQLite via SQLAlchemy's `schema_translate_map`.

One ordering trap, worth recording because the failure is not obvious: Alembic creates its
own version table *before* running the first revision, and that table lives in `trading`. So
the schema has to exist before Alembic touches anything — `env.py` creates it, not the
migration. Rendering the SQL offline is what surfaced this; the generated script had
`CREATE TABLE trading.alembic_version` above `CREATE SCHEMA trading`.

The emptiness guard survives in `app/persistence/legacy.py`, unwired, for the future cleanup
milestone. It is kept and tested now, while there is no pressure on it, rather than written
in a hurry on the day someone decides to delete 47,500 rows.

## 5. RLS posture

- RLS **enabled** on every table this platform creates, in the same migration that creates it
- An explicit `service_role` full-access policy per table — technically redundant, since
  `service_role` bypasses RLS, but it documents intent in the schema itself and keeps the
  "RLS enabled, zero policies" lint from looking like an oversight
- **Nothing granted to `anon` or `authenticated`**, on either the schema or its tables. Under
  Postgres RLS, absence of a permissive policy is a deny. The browser is not a database
  client here; it talks to FastAPI, which holds the service-role credential server-side.

The 30 legacy tables keep RLS disabled — a deliberate, recorded decision, not an oversight.
Securing them is tracked separately, since doing it here would mean changing the access
posture of an application this change is not otherwise touching.

## 6. What `/health` is for

Not a liveness probe. It's the seam report: app version, database connectivity and current
Alembic revision, and per-provider LLM configuration status. Wiring problems in a
multi-provider, multi-service stack are otherwise invisible until a feature fails, and this
is the one endpoint the web shell consumes in this change — so a broken seam shows up in the
UI immediately rather than in a log nobody reads.

Provider status distinguishes **configured** (credentials present) from **reachable**
(responded to a probe), because "the key is set" and "the server is up" fail differently and
a local Ollama being down is not the same problem as an absent Anthropic key.

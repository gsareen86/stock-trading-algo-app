# Project: agentic swing + long-term equity platform (Indian markets)

The system map. Read this before `openspec/AGENTS.md`'s workflow makes sense.

## What this is

A paper-trading research and decision platform for **swing/positional** and **long-term**
investing in Indian equities. Four independent strategies each publish their own verdict on
a stock, in plain English, with every claim traceable to the evidence that produced it.

**No intraday.** Dropped entirely and deliberately — it is not coming back.

## Why it was rebuilt

The predecessor grew conversationally to ~25,000 lines and became hard to reason about:
three trading books with three duplicate position ledgers, two unreconciled fundamental
scorers, a config knob settable three different ways with no stated precedence, zero tests,
and docs that had drifted from the code.

The decisive failure was the **confluence scorecard**: four positional strategies were run
and then collapsed into one blended number. A strong score could quietly outvote a failed
hard gate, and nobody could say which strategy liked a name, or why. This rebuild's central
design choice is the direct correction — verdicts stay independent, and disagreement between
strategies is a visible, first-class outcome rather than something averaged away.

## Design principles

Each one fixes a specific, observed failure of the predecessor.

1. **One config source of truth** — typed `pydantic-settings`, one precedence chain, every
   setting documented. *(the #1 tracking pain)*
2. **One ledger abstraction parameterized by book.** *(old app: 3 copies)*
3. **Gates vs scores strictly separated** — hard gates (liquidity, surveillance,
   governance) can never be averaged away by a strong score.
4. **Verdicts are never blended.** *(the confluence-scorecard fix)*
5. **The LLM explains; it never decides.** Verdicts are deterministic and reproducible with
   the LLM off.
6. **Tests are part of done** — pytest from the first module. *(old app: zero tests)*
7. **Paper-only, with one explicit execution boundary** — no stubbed broker classes that
   silently no-op.
8. **Spec before code**; no orphan flags.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, pydantic-settings |
| Persistence | SQLAlchemy + Alembic — SQLite (dev), Supabase Postgres 17 (prod) |
| Agents | LangGraph `StateGraph`; A2A (`a2a-sdk`) for external interop |
| LLM gateway | LiteLLM Router (7 providers) |
| Observability | Langfuse — traces, tokens, cost, prompts |
| Frontend | Next.js 15, TypeScript, Tailwind, shadcn/ui |
| Tests | pytest |

## Repo layout

```
backend/app/
  core/         settings, logging, IST clock
  domain/       pure models: Instrument, Candle, Verdict, Evidence, GateResult, Position
  data/         PORTED plumbing: prices (+ cache), universe, NSE calendar
                (fundamentals and Screener.in scraping land with the screening change;
                 there was never a surveillance module to port — only an orphan table)
  skills/       manifest-driven capabilities, callable by agents
  strategies/   4 independent strategies, each → Verdict
  agents/       LangGraph nodes + A2A adapters
  llm/          LiteLLM gateway, routing, Langfuse wiring
  engine/       cycle orchestration
  books/        swing.py, longterm.py  (share ONE ledger)
  persistence/  SQLAlchemy models + Alembic migrations
  api/          FastAPI routers
backend/tests/
web/            Next.js frontend
openspec/       this living spec
<root pkgs>     LEGACY — read-only, deleted at a tracked milestone
```

## The decision model

Each strategy independently produces one `Verdict`:

```
Verdict:
  strategy_id   minervini | brahma_vishnu_mahesh | fun_tech_momentum | young_momentum
  ticker, as_of
  stance        BUY | WATCH | AVOID          (never a blended number)
  conviction    0-100, scoped to THIS strategy only
  gates         [GateResult]  hard pass/fail, evaluated before scoring
  evidence      [Evidence] {id, metric, value, threshold, passed, source_ref}
  narrative     LLM plain-English findings + recommendation
  trace_id      → Langfuse trace for the narrative call
```

**How traceability actually works.** `evidence` is produced entirely by deterministic
Python; every row carries the observed value, the threshold it was tested against, and a
`source_ref` (price-bar date, filing URL, news item id). The narrative call receives *only*
the evidence list and must cite `evidence.id` inline; it never sees raw prices, so it has
nothing to invent from. A post-generation validator rejects any narrative containing a
number absent from the evidence set. Every sentence a user reads therefore maps to a row
they can click, and the verdict itself reproduces without the LLM.

## The four strategies

| Strategy | Core test |
|---|---|
| **Minervini** | Trend Template + VCP contractions + SEPA |
| **Brahma-Vishnu-Mahesh** | Weekly regime → top-3 sector RS → multi-year base breakout |
| **Fundamental-Technical Momentum** | CANSLIM-style EPS/sales surprise → tight base → volume breakout |
| **Young Momentum** | 1-2-3-4: base breakout → impulse → shallow pause → continuation |

## Agent cycle

```
regime ─→ screen ─→ research ──┬─→ strategy.minervini ────┐
                               ├─→ strategy.bvm ──────────┤
                               ├─→ strategy.fun_tech ─────┼─→ risk ─→ insights
                               └─→ strategy.young_mom ────┘
```

The four strategy nodes fan out **in parallel and never share state** — that isolation is
what makes the verdicts genuinely independent rather than independent-looking. `risk`
applies portfolio gates and sizing; it may veto a verdict but never rewrite one.

Each agent is also wrapped as an **A2A server** exposing an agent card at
`/.well-known/agent-card.json`. For a single-process app this buys nothing today; its value
is letting these agents be driven by, or delegate to, outside agents later. It is a thin
adapter over the LangGraph nodes, deliberately kept as a seam rather than a dependency.

## Skills

Capabilities are packaged in `backend/app/skills/` as a manifest (`name`, `description`,
input/output JSON Schema) plus a handler. One definition is bound both as a LangGraph tool
and as an advertised skill in the agent's A2A card. Adding a skill is one directory and no
orchestration changes. Seed set: `news_research`, `event_calendar`, `filings_scan`,
`peer_compare`.

## LLM routing

Config-driven per task (`LLM_ROUTE__<task>`), so narrative generation can run on a local
model while research runs on a frontier one.

| Provider | Route |
|---|---|
| Anthropic, Gemini, OpenAI | native LiteLLM providers |
| Ollama, LM Studio | native (`ollama/`, `lm_studio/`) |
| llama.cpp, AMD Lemonade | `openai/<model>` + `api_base` (OpenAI-compatible) |

A failed LLM call must never crash a cycle. The gateway carries a circuit breaker and a
disk cache for stable prompts — the two ideas worth keeping from the legacy `llm/client.py`.

## Data & security

SQLAlchemy + Alembic own the schema. Supabase project `zzhvzrxnesibjrklkcis`
(`Stock Trading App`, ap-southeast-2, Postgres 17.6).

**The platform owns the `trading` schema.** The predecessor's 30 tables stay in `public`,
holding ~47,500 rows of real history — 472 trades, 206 positions, 325 signal outcomes and
~20,000 signals — which `backtesting` and `books-ledger-and-analytics` will read. Migrations
never drop, alter or write to a table this platform did not create. SQLite has no schemas, so
the namespace is translated away there; one model definition serves both dialects.

**RLS is mandatory on every table we create.** Enabled *with policies written in the same
migration*, never a bare `ENABLE` (which locks the app out). Nothing is granted to `anon` or
`authenticated`: the backend uses the service role, and the browser never queries Supabase
directly. A non-`public` schema is also not exposed by PostgREST unless opted in.

**Legacy `public` tables: closed, not outstanding.** They still have RLS disabled, and the
Supabase security advisor reports 30 ERRORs for them. This is an accepted risk, decided
deliberately: the data is entirely paper-trading output — no real money, no personal data, no
credentials — so the exposure has no meaningful consequence. Do not re-raise it as a finding,
and do not "fix" it opportunistically. If those tables are ever retired, the guard in
`app/persistence/legacy.py` is what does it.

## Surfaces

| Surface | Answers |
|---|---|
| **Today** | The insights feed — new verdicts, exits, alerts, agent-run summary |
| **Ideas** | Candidates with all four verdicts side by side |
| **Positions** | What I own across both books, thesis + live exit state |
| **Stock** | One name: chart, VCP structure, quality, research, four verdicts |
| **Performance** | By book, by strategy, vs benchmark |
| **Engine** | Config, run history, agent traces, LLM cost, backtest lab |

Insights are delivered **in-app only** — no email, no push, no Telegram.

## Glossary

- **Book** — a capital pool with its own rules. Two exist: `swing`, `longterm`.
- **Gate** — a hard pass/fail check. Never averaged into a score.
- **Evidence** — one measured fact with its threshold and source. The unit of traceability.
- **Verdict** — one strategy's independent opinion on one ticker at one point in time.
- **Conviction** — 0-100 strength *within a single strategy*. Not comparable across them.
- **Stance** — `BUY` | `WATCH` | `AVOID`.
- **Skill** — a manifest-declared capability an agent can call.
- **Cycle** — one end-to-end agent run producing verdicts and insights.
- **IST** — Asia/Kolkata. All market timestamps are IST; all storage is UTC.

## Roadmap

1. `bootstrap-platform-skeleton` ← current
2. `llm-gateway-and-observability`
3. `market-data-foundation`
4. `skills-registry`
5. `verdict-model-and-minervini`
6. `remaining-three-strategies`
7. `verdict-narratives`
8. `agent-graph-and-a2a`
9. `screening-universe-and-gates`
10. `books-ledger-and-analytics`
11. `insights-feed`
12. `backtesting`
13. `gui-shell-and-design-system` → `gui-surfaces`

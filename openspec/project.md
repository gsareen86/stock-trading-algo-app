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
  data/         prices (+ cache), universe, NSE calendar, surveillance lists
  screening/    eligibility filters — turnover floors, surveillance, traceable exclusions
  tools/        manifest-driven capabilities, callable by agents
  strategies/   4 independent strategies, each → Verdict
  agents/       LangGraph nodes + A2A adapters
  llm/          LiteLLM gateway, routing, Langfuse wiring
  engine/       cycle orchestration
  books/        ONE ledger, book as a parameter; portfolio analytics
  risk/         portfolio gates and sizing
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
screen ─→ regime ─→ research ──┬─→ strategy.minervini ────┐
                               ├─→ strategy.bvm ──────────┤
                               ├─→ strategy.fun_tech ─────┼─→ risk ─→ narrate ─→ END
                               └─→ strategy.young_mom ────┘
```

`insights` is absent until `insights-feed` lands. A placeholder node would be inventing
behaviour to be thrown away.

`risk` sits after the fan-in because it needs every verdict to judge portfolio impact. It
returns a decision *about acting* — proceed with a size, or decline with a named gate — and
never touches a verdict: `Verdict` is frozen and its only mutator sets a narrative, so risk
structurally cannot downgrade a BUY. Sizing considers one verdict at a time and never ranks
two against each other; a portfolio layer is exactly where the confluence scorecard would look
reasonable.

**`screen` runs only when the caller names no symbols.** Naming them asks about *those* names,
which is a different question from "what is worth looking at today" — including for a name that
would not have survived a screen. Screening decides eligibility and never ranks: the eligible
set comes back in universe order, and a limit truncates rather than selects.

Three questions are kept apart, and were one number in the predecessor: **should we look at
this** (screening), **can this strategy assess it** (`strategies/gates.py`), **is the setup
attractive** (a strategy's criteria).

Screening the live NIFTY500 costs ~330s on a cold price cache — 499 histories — and is fast on
repeat. The ₹5 crore turnover floor excludes only a handful of NIFTY500 names, as expected: it
earns its place against a wider universe, not this one.

**External MCP tools** (Zerodha Kite) are offered to the research step namespaced by server
(`kite:get_ltp`) and are never registered in `ToolRegistry` — that registry promises an output
schema and evidence-shaped results, which we cannot promise for someone else's server. Any
remote tool whose name contains a mutating verb (`place`, `cancel`, `modify`, `delete`, `exit`,
`square`, `convert`) is refused at discovery and reported: this platform is paper-only
(principle 7), and a research step is not the execution boundary.

The four strategy nodes fan out **in parallel and never share state** — that isolation is
what makes the verdicts genuinely independent rather than independent-looking. `risk`
applies portfolio gates and sizing; it may veto a verdict but never rewrite one.

Each agent is also wrapped as an **A2A server** exposing an agent card at
`/.well-known/agent-card.json`. For a single-process app this buys nothing today; its value
is letting these agents be driven by, or delegate to, outside agents later. It is a thin
adapter over the LangGraph nodes, deliberately kept as a seam rather than a dependency.

## Tools

Capabilities are packaged in `backend/app/tools/` as a manifest (`name`, `summary`,
`description`, input/output JSON Schema) plus a handler. One definition is bound both as a
LangGraph tool and as an entry in the agent's A2A card — where the format's own term for it
is "skill", which is why `to_a2a_skill` keeps that name and nothing else does. Adding a tool
is one directory and no orchestration changes. Seed set: `news_research`, `event_calendar`,
`filings_scan`, `peer_compare`.

`summary` is the selection signal a model reads when choosing among tools, so it must state
both what the tool does **and when to reach for it**; `description` is the longer form for the
A2A card and human readers. External MCP tools (Zerodha Kite) join this set at
`agent-graph-and-a2a` without becoming part of this registry.

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

**Local and hosted providers have separate timeouts.** `LLM_TIMEOUT_SECONDS` (30) is a
hosted-model number; a request still running after it is hung, not slow.
`LLM_LOCAL_TIMEOUT_SECONDS` (300) applies to local rungs, which are an order of magnitude
slower and cost nothing to wait for. Found the first time a 12B model ran on real hardware,
where every narrative call timed out and the feature looked broken rather than slow.

`run-local.ps1` is the supported way to start the stack locally — the routing and timeout
settings are environment variables, so a server started any other way loses them silently.

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
- **Tool** — a manifest-declared capability, executed by the *application* under a JSON
  Schema contract. Lives in `app/tools/<name>/tool.py`. Was called a "skill" until
  `tool-registry`; the distinction below is why it is not.
- **Agent Skill** — Anthropic's artefact: a `SKILL.md` file of procedural knowledge that a
  *model* reads through progressive disclosure. No schema, no handler, no return value. The
  first one arrives with `verdict-narratives`, to teach explanation — never to decide, which
  stays in deterministic gate code.
- **MCP tool** — a tool defined by an *external* server (Zerodha Kite, arriving with
  `agent-graph-and-a2a`) rather than by this repo.

  The three differ by **who executes them**, which is why they must not share a name: a tool
  is called by code and fails with a schema violation you can assert on; an Agent Skill is
  read by a model and fails by being ignored.
- **Cycle** — one end-to-end agent run producing verdicts and insights.
- **IST** — Asia/Kolkata. All market timestamps are IST; all storage is UTC.
- **INR** — the platform's reporting currency, everywhere. LLM vendors are the one exception
  and they bill in USD: the ledger stores their dollars unconverted so a row reconciles
  against an invoice, and `USD_INR_RATE` is applied when that ledger is *read*, never when it
  is written. Same rule as yfinance's `.NS` suffix — a provider artefact, translated at one
  seam. See `app/core/money.py`.

## Roadmap

1. `bootstrap-platform-skeleton`
2. `llm-gateway-and-observability`
3. `market-data-foundation`
4. `skills-registry`
5. `verdict-model-and-minervini`
6. `remaining-three-strategies`
7. `verdict-narratives`
8. `agent-graph-and-a2a`
9. `screening-universe-and-gates`
10. `books-ledger-and-analytics`
11. `insights-feed` ← next
12. `backtesting`
13. `gui-shell-and-design-system` → `gui-surfaces`

Changes that arrive outside this sequence are archived alongside it rather than renumbered:

- `inr-cost-reporting` — report money in rupees. Raised while validating the gateway against
  a local model on real hardware, which is also where the roadmap's numbering stops being the
  only thing that drives work.

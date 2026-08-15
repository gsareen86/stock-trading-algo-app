# Project: stock-trading-algo-app

## What this is

A self-contained **paper-trading** (simulated, no real money) system for the Indian
stock market (NSE), built as one Python process (FastAPI backend + two background
scheduler threads) plus a React dashboard. There is no live-broker execution path
anywhere in the codebase today — see `specs/broker-execution-and-costs/spec.md`.

The system runs **three semi-independent trading "books"**, sharing infrastructure but
each with its own strategies, scoring, position ledger, and exit rules:

| Book | Timeframe | Hold period | Default state |
|---|---|---|---|
| **Intraday** | 15-min candles | same-day, square-off 15:10 IST | always on |
| **Positional / Swing** | daily candles | ~10–30 trading days | off until toggled (`positional_enabled`) |
| **Long-Term** | daily candles | 1–3+ years, thesis-driven exits only | off by default (`LT_BOOK_ENABLED`) |

A stock can be scored for Positional and Long-Term simultaneously; see
`specs/conviction-engine-scoring-routing/spec.md` for how a candidate is routed to
`BOTH` / `POSITIONAL` / `LONG_TERM` / `AVOID`.

Layered on top: an unusually extensive LLM subsystem (six independently-toggleable
intraday features, a concall-research + guidance-ledger pipeline for the positional book,
and a separate news-impact pipeline), plus outcome-tracking/backtesting/calibration
infrastructure meant to eventually validate the many hand-tuned thresholds in the system.

## Why this file exists

This app grew "vibe-coded" — conversationally, one feature at a time — to roughly 25,000
lines of Python + a React frontend, 101 API endpoints, and 35 database tables. At that
size, "what features/config are actually running and how does the app behave" stopped
being answerable by memory or by the README alone. Concretely: the README documented 9
intraday strategies and 7 positional strategy files; the code actually has 10 and 4 (see
Corrected project layout below) — this was found and fixed as part of adopting OpenSpec.

Going forward, **`openspec/specs/` is the source of truth for current behavior**, and
`openspec/changes/` is how behavior changes going forward — see `AGENTS.md`. This file is
the map: architecture, stack, how to run, and — the most direct fix for the tracking
problem — a full inventory of every config/feature-flag and which layer controls it.

## Tech stack

- **Backend**: Python 3.10+, single process, multi-threaded (not microservices).
  FastAPI + Uvicorn (`api/server.py`), served on `:8000` by default.
- **Data/ML**: pandas, numpy, `ta` (technical indicators), yfinance (primary market-data
  source), pyarrow (parquet disk cache), VADER + FinBERT (`transformers`/`torch`) for
  non-LLM sentiment.
- **LLM**: `openai` SDK (used against OpenRouter's OpenAI-compatible endpoint) and
  `anthropic` SDK; provider switable via `LLM_PROVIDER`.
- **DB**: dual backend — SQLite (default, zero-config) or Postgres/Supabase
  (`psycopg[binary]`), selected by `DB_BACKEND`. Schema is defined twice in
  `db/models.py`, once per dialect (`AUTOINCREMENT` vs `SERIAL`) — deliberate, not drift.
- **Scheduling**: two hand-rolled `while True: sleep(N)` daemon threads
  (`scheduler/runner.py`, `positional/runner.py`). `APScheduler` is in `requirements.txt`
  but never imported anywhere — declared, unused.
- **Frontend**: React 19 + TypeScript + Vite 8 + Tailwind v4 + Recharts. No router, no
  state-management library — one `App.tsx` with client-side page-switching. npm-managed,
  independent of the Python dependency set.
- **Package management**: pip + `requirements.txt` (no lockfile, `>=` floors only).
  `nsepython` is also declared but unused — all NSE calls are hand-rolled `requests`.
- **Testing**: **there is no automated test suite** — no `tests/`, no CI, no pytest
  config anywhere. `scripts/verify_new_strategies.py` is a manually-run assertion script,
  not a discovered/CI test. Specs in this directory are written directly from code
  behavior and should be treated as needing manual/exploratory verification, not
  as backed by an existing suite.

## How to run

```bash
pip install -r requirements.txt
python main.py --init             # create DB, seed bot_control row, then exit
python main.py                    # full app: FastAPI + intraday thread + positional thread
```
Other modes: `--runner-only`, `--dashboard-only`, `--positional-only`, `--reset`
(destructive DB wipe). Frontend dev server: `cd frontend && npm run dev` (Vite on
`:5173`, proxies API calls to `:8000`).

## Architecture map

```
main.py
  ├─ Thread: scheduler/runner.py     — intraday loop, ~15 min poll (adaptive)
  ├─ Thread: positional/runner.py    — positional loop, time-of-day scheduled
  └─ FastAPI server (api/server.py)  — ~101 endpoints, serves the React dashboard

Scoring/routing spine (specs/conviction-engine-scoring-routing):
  positional strategies + Minervini scanner  →  technical/timing pillar
  specs/fundamentals-quality-scoring         →  quality + valuation pillars
  specs/concall-research-and-guidance-ledger →  management pillar (once researched)
  specs/news-sentiment-analysis              →  sentiment pillar
                    ↓
     two-axis Timing/Durability scorecard → BOTH | POSITIONAL | LONG_TERM | AVOID
                    ↓                              ↓                ↓
        specs/positional-swing-trading   specs/long-term-book   (watch only)
```

Cross-cutting: `specs/market-data-ingestion` (all books read through it),
`specs/market-hygiene-and-surveillance` (gates positional + long-term; **not** intraday —
named explicitly as a gap in that spec), `specs/broker-execution-and-costs` (cost
simulation + broker stubs), `specs/llm-platform-and-feature-toggles` (shared LLM client
+ six toggles), `specs/data-persistence`, `specs/outcome-tracking-and-backtesting`.

Each book keeps its own position-sizing/exit logic and its own ledger tables — this is
real duplication, not a shared risk engine:
- Intraday: `engine/risk_manager.py` + `engine/atr_exits.py` → `positions`/`trades`
- Positional: `positional/risk.py` → `pos_positions`/`pos_trades`
- Long-term: sizing/exits inline in `longterm/book.py` → `lt_positions`/`lt_trades`

## Config & feature-flag inventory

Every tunable lives in `config.py` (~640 lines). The tracking difficulty the user
reported is real and specific: **which layer wins for a given knob is inconsistent, not
uniform** — some flags are hardcoded only, some also read an `.env` override, and a
separate handful are live-editable from the dashboard (Control Center) via the
`bot_control` DB row, independent of both. See
`specs/configuration-and-feature-flags/spec.md` for the exact resolution mechanism and
Requirements/Scenarios. This table is the enumeration; that spec is the contract.

**Layer legend**: `code` = hardcoded constant in `config.py`, no override · `env` =
`config.py` default overridable via `.env` · `db` = live-editable via the `bot_control`
row at runtime (takes effect without restart), independent of `config.py`/`.env`.

### Master on/off switches
| Flag | Layer | Default | Controls |
|---|---|---|---|
| `positional_enabled` (bot_control column) | db | `0` (off) | Whole positional/swing module |
| `LT_BOOK_ENABLED` | env | `False` | Whole Long-Term book — separate paper pool, tranches, thesis stops |
| `ENABLE_ML_META_MODEL` | code | `False` | Phase-2 placeholder — **no implementation exists** |
| `ENABLE_ADAPTIVE_WEIGHTS` | code | `False` | Phase-2 placeholder — **no implementation exists**; do not confuse with `LLM_ENABLE_META_WEIGHTS` below, which is implemented and on |
| `ENABLE_FINBERT` | code | `True` | Heavier finance-tuned sentiment model vs. VADER-only fallback |
| `LLM_ENABLE_SENTIMENT` / `_VETO` / `_REGIME` / `_EVENTS` / `_EOD_REVIEW` / `_META_WEIGHTS` | code | all `True` | Independently disable any of the 6 intraday LLM features |
| `POSITIONAL_CONCALL_RESEARCH_ENABLED` | env | `True` | Concall/guidance research pipeline |
| `POSITIONAL_LLM_RESEARCH_ENABLED` (also `bot_control.positional_llm_research_enabled`) | env **and** db | `True` | Positional LLM research — two independent switches for the same concept |
| `POSITIONAL_SWAP_ENABLED` (also `bot_control.positional_swap_enabled`) | env **and** db | `True` | Positional opportunity-swap logic — two independent switches |
| `GUIDANCE_EXTRACTION_ENABLED` | code | `True` | Guidance-ledger extraction |
| `POSITIONAL_MANAGEMENT_AUTO_EXIT` | env | `False` | Whether a bad management score forces an exit vs. advisory-only |
| `UNIVERSE_WEEKLY_REFRESH_ENABLED` | env | `True` | Saturday Screener-pipeline universe refresh |
| `POSITIONAL_EVENT_GUARD_ENABLED` | code | `True` | Deterministic NSE-calendar entry guard |
| `UNIVERSE_EXCLUDE_SURVEILLANCE` | code | `True` | ASM/GSM exclusion in hygiene gate |

### Runtime (dashboard-editable, `bot_control` row, `db/models.py`)
`status`, `mode` (`manual`/`auto`/`dry_run`), `max_open_positions`, `risk_per_trade_pct`,
`stop_loss_pct`, `take_profit_pct`, `min_composite_score`, plus the three `env`**and**`db`
flags above. Falls back to 5 specific `config.py` constants only if the `bot_control` row
itself is missing (normally seeded by `python main.py --init`) — see the configuration
spec for the exact fallback shape.

### Capital & risk (code, some read by `env`-backed helper functions elsewhere)
`INITIAL_CAPITAL` ₹1,00,000 · `POSITIONAL_CAPITAL` ₹1,00,000 (separate pool) ·
`LT_CAPITAL` ₹1,00,000 (separate pool) · `RISK_PER_TRADE_PCT` 4% (intraday, `db`
overridable) · `POSITIONAL_RISK_PCT_POOL` 1% · full per-book ATR multiplier / stop /
target constants — see each book's own spec rather than duplicating the full list here.

### LLM provider & keys (env)
`LLM_PROVIDER` (`openrouter` default / `anthropic` / `ollama`), `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OLLAMA_MODEL`, `OLLAMA_BASE_URL`,
`OLLAMA_REQUEST_TIMEOUT_S`. Missing key/package silently disables LLM features — bot
falls back to FinBERT/VADER, not an error.

### Notifications / broker (env)
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (empty = disabled, silently) · `POSITIONAL_BROKER`
(`paper` default; `sharekhan`/`zerodha` are accepted values but both fall back to paper —
see `specs/broker-execution-and-costs`) · `SHAREKHAN_*`, `ZERODHA_*` keys (currently inert).

**Known inconsistency**: `.env.example` documents only `DB_BACKEND`/`SUPABASE_DB_URL`/
`SUPABASE_URL`; `.env.template` documents the LLM/Telegram/broker vars but not the DB
ones. A contributor reading only one will miss real options in the other. Not yet fixed
as part of this change — flagged here so it isn't lost.

## Corrected project layout

The README's project-layout section (as of this change) undercounts strategies. Current
actual layout, one line per package with what it owns:

```
config.py            ALL tunables (see inventory above) — edit here, not scattered
main.py               entry point; argparse mode selection; starts 2 daemon threads + API
api/server.py          ~101 FastAPI routes — all business logic imported from below
data/                  market data: fetcher (yfinance+parquet cache), universe (NIFTY500 +
                        full-NSE-master), fundamentals (intraday scorer), hygiene (gates),
                        news_scraper (RSS), nse_calendar (events)
strategies/            10 INTRADAY strategies (not 9 — README undercounts; includes
                        vwap_momentum.py, the single highest-weighted strategy) + base.py
positional/            swing module: scanner (Minervini+VCP), 4 real strategy files in
                        strategies/ (not 7 — README names 7 files that don't exist),
                        scorer/pillars (scoring), risk, runner, market_regime, ipo,
                        sectors, universe*, broker (stub), alerts (Telegram), research/
                        concalls/guidance (LLM research pipeline)
longterm/               quality (5-bucket scorer), screener_scraper, universe, book
                        (Long-Term book), tasks
engine/                 intraday mechanics: paper_broker (cost sim), portfolio (ledger),
                        atr_exits, risk_manager
scoring/composite.py    intraday-only composite (tech+fundamental+sentiment blend)
scheduler/runner.py     intraday main loop
llm/                    shared client (+circuit breaker) + 6 toggleable features
news_impact/            separate LLM pipeline: sector-tag, cluster, severity, alerts
nlp/sentiment.py        VADER/FinBERT path (independent of llm/sentiment.py)
analytics/              metrics (Sharpe/Sortino/etc.), outcomes (forward returns),
                        calibration (advisory threshold report)
backtest/engine.py      walk-forward backtester — positional/swing only, no intraday
db/                     models (dual-backend schema), migrate_sqlite_to_supabase
scripts/                debug/diagnostic CLIs — not a test suite
frontend/               React/Vite/TS SPA, 12 pages matching the dashboard sidebar
docs/                   INVESTMENT_ENGINE_DESIGN.md (as-built conviction-engine record)
openspec/               this living specification
```

## Glossary

- **Timing (Axis A)** — does a valid technical entry exist *now*? (the positional
  technical-pillar/confluence score)
- **Durability (Axis B)** — can the business *compound* over time? (blend of quality +
  valuation + management pillars)
- **Confluence** — number of positional strategies agreeing on a BUY; more agreement →
  bonus added to the technical pillar
- **Horizon label** — `BOTH` / `POSITIONAL` / `LONG_TERM` / `AVOID`, the output of
  crossing Timing and Durability against their "strong" thresholds
- **T1** — first (partial) profit target; a fraction of the position is closed there and
  the stop trails on the remainder
- **HWM** — high-water mark, used as the trailing-stop reference after T1
- **Thesis stop** (Long-Term book only) — an exit triggered by a fundamental/guidance
  deterioration rather than a price level or time stop
- **Fail-open** — a gate (event guard, surveillance list) that does not block when its
  underlying data is missing/stale, only when it has a positive match

## Conventions for future work

- Read the relevant `openspec/specs/<capability>/spec.md` before changing behavior in
  that area.
- Any behavior change goes through `openspec/changes/<id>/` (proposal → tasks → delta
  spec) before code changes — see `AGENTS.md`.
- `config.py` stays the single place new tunables are declared; note in this file's
  inventory (above) which layer(s) it participates in.
- New capabilities get a new `specs/<capability>/` folder, not a bigger existing one —
  keep the boundaries drawn in this file's architecture map.

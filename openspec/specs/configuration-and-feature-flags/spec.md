# Configuration & Feature-Flag Resolution

Status: **mechanism baseline** — not a near-term work area, but given full
Requirement/Scenario treatment because this is the user's explicitly named pain point
("hard to track what configurations are running"). This spec covers the *resolution
mechanism*; `openspec/project.md`'s config inventory table is the enumeration of
individual flags. Read both together.

## Overview

There is no single, uniform configuration system in this codebase. A given knob may be
resolved from one, two, or three independent layers depending on which knob it is — this
is a per-flag inconsistency, not a uniform stack a reader can learn once and apply
everywhere.

- **`code`** — a hardcoded constant in `config.py`, no override mechanism.
- **`env`** — a `config.py` constant whose default is `os.environ.get("X", default)`,
  overridable via `.env`/the process environment.
- **`db`** — a column on the single-row `bot_control` table, read live at call time via
  `engine/risk_manager.py::get_runtime_params()`, editable from the dashboard Control
  Center without a restart.

## Requirements

### Requirement: `.env` is loaded once, before any `env`-layer default is computed
The system MUST call `load_dotenv()` at the top of `config.py`, before any
`os.environ.get(...)`-backed constant is defined, so that values set in `.env` are
visible when those module-level constants are computed at import time.

#### Scenario: dotenv package missing
- GIVEN the `python-dotenv` package is not installed
- WHEN `config.py` is imported
- THEN the `ImportError` is caught and swallowed — `.env` is simply not loaded, and every
  `env`-layer constant falls through to its hardcoded default unless the variable is set
  another way (e.g. the process environment directly)

### Requirement: `db`-layer parameters fall back to `config.py` only if the `bot_control` row is entirely absent
The system MUST read runtime parameters (`max_open_positions`, `risk_per_trade_pct`,
`stop_loss_pct`, `take_profit_pct`, `min_composite_score`, plus
`positional_llm_research_enabled` and `positional_swap_enabled`) from the single
`bot_control` row (`id=1`) on every call to `get_runtime_params()` — there is no caching,
so a dashboard edit takes effect on the very next read.

#### Scenario: Normal operation — row exists
- GIVEN `python main.py --init` has run (which seeds the `bot_control` row)
- WHEN `get_runtime_params()` is called
- THEN it returns the live row's values, reflecting any dashboard edits made since the
  last read

#### Scenario: Row entirely missing — falls back to a narrower set of config.py constants
- GIVEN no row exists in `bot_control` at all (only reachable before first `--init`)
- WHEN `get_runtime_params()` is called
- THEN it returns a dict built from exactly 5 `config.py` constants
  (`MAX_OPEN_POSITIONS`, `RISK_PER_TRADE_PCT`, `STOP_LOSS_PCT`, `TAKE_PROFIT_PCT`,
  `MIN_COMPOSITE_SCORE`) — this fallback dict does **not** include
  `positional_llm_research_enabled`/`positional_swap_enabled`/`positional_enabled` keys,
  so a caller reading those specific keys from the fallback path would `KeyError` rather
  than silently getting a default. In practice this path is only reachable before the DB
  has ever been initialized.

### Requirement: A flag with both `env` and `db` layers has two independent switches for one concept, not one switch with two entry points
The system MUST be understood as having `POSITIONAL_LLM_RESEARCH_ENABLED` (env,
`config.py`) and `bot_control.positional_llm_research_enabled` (db) as two separate
values that are not automatically kept in sync with each other, and likewise for
`POSITIONAL_SWAP_ENABLED`/`bot_control.positional_swap_enabled`.

#### Scenario: env and db disagree
- GIVEN `.env` sets `POSITIONAL_LLM_RESEARCH_ENABLED=False` but the dashboard's
  `bot_control.positional_llm_research_enabled` column is `1` (its schema default)
- WHEN code checks "is LLM research enabled"
- THEN the answer depends entirely on which of the two flags that specific call site
  reads — there is no single merged source of truth for this concept today

### Requirement: Most `env`-named constants are config-with-env-override, not first-class deployment inputs
The system MUST be read as: the majority of `os.environ.get(...)`-backed constants in
`config.py` (e.g. `POSITIONAL_RESEARCH_LIMIT`, `POSITIONAL_MANAGEMENT_VETO_SCORE`,
`UNIVERSE_SOURCE`) exist so a value *can* be overridden without a code change, not because
they're documented, expected per-deployment inputs. Only a small subset — DB backend
selection, LLM provider/keys, Telegram credentials, broker keys — are genuinely meant to
be set per-deployment, and only those are covered by `.env.example`/`.env.template`.

#### Scenario: An override-capable constant with no documented env var
- GIVEN a constant like `POSITIONAL_CONCALL_MAX_PAGES` is `env`-backed in `config.py`
- WHEN a new contributor looks at `.env.example` or `.env.template` to find configurable
  options
- THEN they will not find it listed in either file — its overridability is only visible
  by reading `config.py` directly

## Known gaps / gotchas

- `.env.example` and `.env.template` document different, non-overlapping subsets of the
  real environment variables (DB-backend vars only in one, LLM/Telegram/broker vars only
  in the other) — a contributor following just one misses real options in the other. Not
  fixed as part of this change; flagged so it's tracked.
- No single file enumerates, for every flag, which of `code`/`env`/`db` layers apply —
  `openspec/project.md`'s inventory table is the closest thing that exists today, and it
  was written as part of this same change specifically to close that gap.
- `ENABLE_ADAPTIVE_WEIGHTS`/`ENABLE_ML_META_MODEL` (code layer, both `False`, Phase-2
  placeholders with no implementation) are easily confused with the implemented,
  on-by-default `LLM_ENABLE_META_WEIGHTS` — same-sounding names, different code paths,
  different actual status.

## Source modules

`config.py` (~640 lines, ~27 `os.environ.get` call sites), `engine/risk_manager.py` (59
lines — the `db`-layer read/fallback path), `db/models.py` (`bot_control` schema).

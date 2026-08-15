# LLM Platform & Feature Toggles

Status: baseline — not yet exercised through a change under `openspec/changes/`.

The shared multi-provider LLM client plus the six independently-toggleable intraday LLM
features built on top of it. Split from `specs/concall-research-and-guidance-ledger`,
which is positional-specific business logic built on this same client.

## Requirements

### Requirement: Multi-provider client with circuit breaker and disk caching
The system MUST support Anthropic, OpenRouter (default — free-tier models, no Anthropic
account required), and local Ollama as interchangeable LLM providers
(`LLM_PROVIDER`), MUST open a circuit breaker after 3 consecutive 429 (rate-limit)
responses with a 10-minute cooldown, and MUST cache responses to disk with a per-cache-key-prefix
TTL (`LLM_CACHE_TTL_HOURS` — e.g. 24h for events, 7d for sentiment, 30d for a news
article's sector tag, which never changes).

#### Scenario: Circuit breaker open
- GIVEN 3 consecutive 429 responses from the active provider
- WHEN another LLM call is attempted within the 10-minute cooldown
- THEN the call is short-circuited (not sent) until the cooldown elapses

### Requirement: Missing key or package disables LLM features without erroring
The system MUST treat a missing API key or missing SDK package as "LLM features
disabled," falling back to FinBERT/VADER for sentiment and skipping veto/regime/events/
eod-review/meta-weights outright, rather than raising an error that stops the bot.

#### Scenario: No API key configured for the selected provider
- GIVEN `LLM_PROVIDER=anthropic` but `ANTHROPIC_API_KEY` is unset
- WHEN an intraday cycle runs and would normally call the LLM veto/regime/sentiment steps
- THEN those steps are skipped (or fall back to FinBERT/VADER for sentiment) and the
  cycle continues normally — a missing key does not crash or halt trading

### Requirement: Six independently-toggleable intraday LLM features
The system MUST allow each of the following to be disabled independently via its own
`LLM_ENABLE_*` flag (all default `True`), without needing to disable the LLM client
entirely: `veto` (pre-trade PROCEED/REDUCE/SKIP gate — described in-code as "the
highest-leverage LLM feature for P&L"), `regime` (narrative BULLISH/BEARISH/VOLATILE/AVOID
market mood), `events` (earnings/corporate-action extraction from news, intraday path
only — positional uses the deterministic NSE calendar instead), `eod_review` (daily
post-trade analysis + config-change recommendations, written for human review, never
auto-applied), `meta_weights` (hourly adaptive strategy-weight rebalance, clamped ±0.15
from baseline), and `sentiment` (LLM sentiment path — see `specs/news-sentiment-analysis`
for its fallback chain).

#### Scenario: EOD review recommendations are never applied automatically
- GIVEN `llm/eod_review.py` produces a config-change recommendation
- WHEN the recommendation is generated
- THEN it is written to the database for human review only — no code path applies it to
  `config.py` or `bot_control` automatically

### Requirement: `LLM_ENABLE_META_WEIGHTS` is distinct from the unimplemented `ENABLE_ADAPTIVE_WEIGHTS`
The system's actual adaptive-strategy-weight mechanism is `llm/meta_weights.py`, gated by
`LLM_ENABLE_META_WEIGHTS` (implemented, on by default). The similarly-named
`ENABLE_ADAPTIVE_WEIGHTS` config flag is a separate, unimplemented Phase-2 placeholder
(always `False`, no corresponding code found) and MUST NOT be confused with it.

#### Scenario: Someone sets `ENABLE_ADAPTIVE_WEIGHTS = True` expecting adaptive weights
- GIVEN a developer flips `ENABLE_ADAPTIVE_WEIGHTS` to `True` in `config.py`, believing
  this turns on strategy-weight adaptation
- WHEN the intraday cycle runs
- THEN nothing observably changes — no code reads this flag to alter strategy weights;
  the actual mechanism (`LLM_ENABLE_META_WEIGHTS`) is a separate flag, already on by
  default

## Known gaps / gotchas

- Name collision risk: `ENABLE_ADAPTIVE_WEIGHTS`/`ENABLE_ML_META_MODEL` (both
  unimplemented Phase-2 placeholders, always `False`) sit right next to
  `LLM_ENABLE_META_WEIGHTS` (implemented, on) in `config.py` — see
  `openspec/project.md`'s config inventory.
- LLM pricing table (`LLM_PRICING_USD_PER_MTOK`) is a manually-maintained lookup used
  only for the LLM Usage dashboard's cost *estimate* — it does not affect any trading
  decision, and goes stale whenever a provider changes its rate card.

## Source modules

`llm/client.py`, `llm/observability.py`, `llm/veto.py`, `llm/regime.py`, `llm/events.py`,
`llm/eod_review.py`, `llm/meta_weights.py`, `llm/sentiment.py`.

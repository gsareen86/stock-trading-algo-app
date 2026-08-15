# News-Impact LLM Pipeline

Status: baseline — not yet exercised through a change under `openspec/changes/`.

A second, separate LLM-driven pipeline over the news feed: sector-tags articles, clusters
related ones, and assesses per-ticker impact severity, writing alerts consumed by the
dashboard's "News & Alerts" tab and by the positional exit stack. Deliberately kept split
from `specs/news-sentiment-analysis` — confirmed non-integrated, separate code paths.

## Requirements

### Requirement: Articles are sector-tagged and clustered before severity assessment
The system MUST tag each article with a sector (LLM-assisted, with a deterministic
fallback when the LLM is unavailable/disabled) and cluster related articles before
assessing per-ticker impact severity — avoiding scoring near-duplicate articles about the
same event as independent signals.

#### Scenario: Three articles cover the same event
- GIVEN three separate RSS articles report the same corporate event for one ticker
- WHEN the pipeline processes them
- THEN they are clustered into one group before severity assessment, rather than
  producing three independent severity/alert entries for the same underlying event

### Requirement: Per-ticker throttle, not a global one
The system MUST throttle news-impact assessment per ticker
(`NEWS_IMPACT_PER_TICKER_THROTTLE_MIN`, 240 min in `config.py`'s comment / currently 60
min via `NEWS_IMPACT_THROTTLE_MIN`) rather than with a single global throttle — a global
throttle would let one ticker's news delay assessment of an unrelated ticker's news.

#### Scenario: Two unrelated tickers get news the same minute
- GIVEN ticker A was just assessed and is within its per-ticker throttle window, and
  ticker B (unrelated) has fresh news and is outside its own throttle window
- WHEN the next assessment pass runs
- THEN ticker B is assessed normally — A's throttle has no effect on B

### Requirement: Critical direct news can freeze same-day trading for a name
The system MUST support a same-day freeze on a ticker when a critical, directly-linked
negative news item is assessed, and MUST default to an exit-review bias
(`REVIEW_EXIT`) for held positions on critical direct linkage, per the positional exit
stack (`specs/positional-swing-trading`).

#### Scenario: Critical direct news on a held position
- GIVEN a held positional position has a news item assessed as critical severity with
  direct linkage to that ticker
- WHEN the assessment completes
- THEN the position is flagged `REVIEW_EXIT` (default-to-exit bias) the same day, rather
  than waiting for the next scheduled exit check

## Known gaps / gotchas

- Entirely separate from `specs/news-sentiment-analysis`'s LLM/FinBERT/VADER sentiment
  scoring — two LLM-touching systems read the same underlying `news` table but do not
  share scoring logic or output.
- A second, DB-only alert system (`news_impact_alerts` table, `/api/alerts/*` endpoints)
  exists in parallel with Telegram alerts (`specs/positional-swing-trading`) — these are
  independent notification channels, not one unified alert system.

## Source modules

`news_impact/pipeline.py`, `news_impact/linkage.py`, `news_impact/llm_tasks.py`,
`news_impact/store.py`, `news_impact/schemas.py`.

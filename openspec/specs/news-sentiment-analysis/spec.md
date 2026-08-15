# News & Sentiment Analysis

Status: baseline — not yet exercised through a change under `openspec/changes/`.

RSS ingestion plus a three-way sentiment scoring fallback chain (LLM → FinBERT → VADER).
Feeds the intraday sentiment gate, the positional sentiment pillar, and (separately) the
news-impact pipeline (`specs/news-impact-llm-pipeline`, a distinct system).

## Requirements

### Requirement: RSS scraping and ticker matching
The system MUST scrape a fixed set of RSS feeds (MoneyControl, Economic Times, LiveMint,
Business Standard — `config.NEWS_SOURCES`) on a refresh interval (`NEWS_REFRESH_MIN`, 30
min) and MUST match articles to tickers by name, avoiding false matches on common-word
ticker symbols (e.g. OIL, PERSISTENT) — this matcher has been fixed at least once per
commit history, indicating it's an easy thing to regress.

#### Scenario: Article mentions a common English word that is also a ticker symbol
- GIVEN an article's body contains the word "oil" in its ordinary English sense (not
  referring to the ticker OIL)
- WHEN the ticker matcher processes the article
- THEN it must not tag that article as being about the OIL ticker on a bare
  case-insensitive substring match — this exact failure mode was fixed once already (see
  commit history) and is the kind of regression a future change to the matcher could
  reintroduce

### Requirement: Sentiment scoring prefers LLM, falls back to FinBERT/VADER
The system MUST prefer LLM-based batch sentiment scoring (`LLM_ENABLE_SENTIMENT`, chunks
of up to 20 articles per call, capped at `LLM_SENTIMENT_MAX_ITEMS_PER_RUN` (120) items per
run) when enabled, and MUST fall back to FinBERT (`ENABLE_FINBERT`, finance-tuned,
heavier) or VADER (always available, lightest) for any article beyond that cap or when
the LLM path fails or is disabled.

#### Scenario: Per-run item cap exceeded
- GIVEN more than 120 sentiment-eligible articles in a run
- WHEN sentiment scoring executes
- THEN articles beyond the cap are scored by FinBERT/VADER, not skipped

### Requirement: Sentiment is time-decayed, not a flat window average
The system MUST weight more recent articles exponentially higher when aggregating
sentiment for a ticker, with a half-life of `SENTIMENT_HALF_LIFE_HOURS` (72h / 3 days) —
not a flat mean over a fixed lookback window.

#### Scenario: Old vs. fresh article
- GIVEN one 6-day-old article and one same-day article with opposite sentiment
- WHEN aggregated sentiment is computed
- THEN the 6-day-old article (2 half-lives elapsed) contributes roughly 25% of the weight
  of the fresh article, not an equal share

## Known gaps / gotchas

- `nlp/sentiment.py` (VADER/FinBERT) and `llm/sentiment.py` (LLM-based) are two separate
  modules implementing conceptually the same "score this text" function with different
  mechanisms — the fallback chain between them is real but not obvious from file layout
  alone.
- This capability is distinct from `specs/news-impact-llm-pipeline` (`news_impact/*`),
  which is a separate, non-integrated pipeline over the same underlying news feed.

## Source modules

`nlp/sentiment.py`, `data/news_scraper.py`, `llm/sentiment.py`.

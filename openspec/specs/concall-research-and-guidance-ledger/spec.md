# Concall Research & Guidance Ledger

Status: baseline — not yet exercised through a change under `openspec/changes/`.

Positional-book-specific "buy-side analyst" pipeline: scrapes Screener.in Pros/Cons plus
concall transcripts/investor-presentation PDFs, has an LLM produce a management
score/verdict, extracts structured forward guidance, and reconciles that guidance against
actuals next quarter into a credibility score. Built on the shared LLM platform
(`specs/llm-platform-and-feature-toggles`) but is business logic specific to this book,
kept as a separate capability.

## Requirements

### Requirement: Research combines scraped fundamentals with concall/PDF extraction
The system MUST scrape Screener.in Pros/Cons and announcements plus the latest concall
transcript or investor-presentation PDF (`positional/concalls.py`, capped at
`POSITIONAL_CONCALL_MAX_PAGES`, 40), map-reducing long transcripts through the LLM in
chunks (`POSITIONAL_RESEARCH_CHUNK_CHARS`, 80,000 chars), and cache the result for
`POSITIONAL_CONCALL_CACHE_DAYS` (25) days before re-researching.

#### Scenario: Research requested within the cache window
- GIVEN a ticker was researched 10 days ago (within the 25-day cache TTL)
- WHEN research is requested for it again (e.g. by a fresh technical trigger)
- THEN the cached research is reused rather than re-scraping and re-running the LLM
  pipeline

### Requirement: Research refresh is decoupled from technical triggers
The system MUST re-run research over open positions, the watchlist, and the recent
shortlist on a daily schedule (`POSITIONAL_RESEARCH_REFRESH_TIME`, 08:30 IST) regardless
of whether any technical trigger fired, so holdings pick up new quarterly concalls as they
publish (staggered across the quarter, not tied to a scan event).

#### Scenario: Held position with no new technical signal
- GIVEN a stock has been held for 40 days with no new strategy signal firing on it
- WHEN the 08:30 research refresh runs and that stock's concall cache has expired since a
  new quarterly concall was published
- THEN it is re-researched as part of the daily refresh, independent of the EOD technical
  scan not having touched it

### Requirement: A management score can veto a buy regardless of technicals
The system MUST veto a positional buy when the management score is at or below
`POSITIONAL_MANAGEMENT_VETO_SCORE` (25.0), independent of how strong the technical/timing
signal is.

#### Scenario: Strong technical setup, poor management read
- GIVEN a ticker has 2+ strategies firing (high technical confluence) but a management
  score of 20 (below the veto threshold)
- WHEN the entry decision is made
- THEN the buy is vetoed on management grounds regardless of the technical strength

### Requirement: Guidance is extracted as structured data and reconciled against actuals
The system MUST extract guidance line items (metric, guided value/band, horizon) from the
"Forward Outlook & Management Guidance" section of research output into the
`guidance_ledger` table, and MUST reconcile each item against next-quarter actuals
(sourced from Screener's quarterly section) as `MET` / `BEAT` / `MISSED` /
`UNVERIFIABLE` once results are published.

#### Scenario: Reconciliation before next results
- GIVEN a guidance item was extracted this quarter and next quarter's results have not
  yet been published
- WHEN the guidance ledger is queried
- THEN `delivered`/`actual_value`/`reconciled_at` remain `NULL` — a first-quarter guidance
  item is un-reconciled by design, not an error state

### Requirement: Credibility blends LLM read with delivery record, only after enough history
The system MUST compute a rolling 8-quarter, recency-weighted hit-rate credibility score,
and MUST NOT blend it into the management pillar until at least 2 quarters have been
reconciled — before that, the management pillar is the LLM read alone. Once eligible, the
pillar blends `0.7×LLM_read + 0.3×credibility` (`GUIDANCE_CREDIBILITY_WEIGHT`). Two
consecutive `MISSED` on the same metric triggers a long-term-book thesis-stop review
(`specs/long-term-book`).

#### Scenario: First quarter of guidance tracking
- GIVEN a newly-researched ticker has zero reconciled guidance quarters yet
- WHEN its management pillar is computed
- THEN it equals the LLM's qualitative read alone — the credibility blend does not apply
  until ≥2 quarters have been reconciled, so a name can't be penalized or boosted by a
  credibility score with no track record behind it

## Known gaps / gotchas

- This is the closest existing mechanism to "management track record: guidance vs.
  delivery," one of the items named in the earlier fundamental-analysis enhancement
  request — but it lives here, scoped to the positional/LT pipeline, not inside either
  fundamental scorer (`specs/fundamentals-quality-scoring`). An enhancement wanting this
  signal should surface/reuse this ledger rather than rebuild it.
- Research and guidance extraction both depend on the shared LLM client
  (`specs/llm-platform-and-feature-toggles`) inheriting its fail-soft behavior — if the
  LLM is unavailable, research silently doesn't run rather than erroring, which also
  means guidance extraction silently doesn't happen that cycle.

## Source modules

`positional/research.py`, `positional/concalls.py`, `positional/guidance.py`.

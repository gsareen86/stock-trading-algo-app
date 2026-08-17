# Tasks: screening-universe-and-gates

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: screening (new), agent-graph (ADDED), platform-api (ADDED), market-data (ADDED)

## Data
- [x] `app/data/resources/surveillance.json` — ASM/GSM symbols with an `as_of` date
- [x] `app/data/surveillance.py` — load lists, report their age

## Screening
- [x] `app/screening/filters.py` — turnover floor, price floor, minimum history, surveillance
- [x] Median rupee turnover, not share count
- [x] `app/screening/screener.py` — apply filters, return eligible + excluded-with-reasons
- [x] Exclusions carry filter id, measured value, threshold and `source_ref`
- [x] No ranking anywhere

## Graph
- [x] `screen` node ahead of `research`
- [x] Skipped when the caller supplied symbols explicitly

## API
- [x] `GET /universe` — snapshot, origin, exclusions
- [x] `POST /screen` — eligible names and why the rest were removed
- [x] `POST /cycles/run` accepts a screen instead of symbols

## Tests
- [x] A thin stock fails the turnover floor; a liquid one passes
- [x] Median resists a single block-deal day
- [x] A surveillance-listed name is excluded
- [x] Stale surveillance data is reported, not hidden
- [x] Every exclusion names its filter, value and threshold
- [x] The screener produces no ordering by quality
- [x] Explicit symbols bypass screening

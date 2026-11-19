# discovery

Top-down daily-driver discovery across the Nifty 750 universe: sector rotation, movers, per-strategy candidate ranking, quality facets, watchlist tracking, morning briefing, and counted-work progress streaming.

Implemented in `backend/app/discovery/`, `backend/app/data/yfinance_quality.py`, and `backend/app/agents/`.

### Requirement: Universe defaults to Nifty Total Market (Nifty 750)
The default investable universe snapshot MUST cover the Nifty Total Market (Nifty 750) constituent list, falling back to a bundled constituent list when live NSE fetching fails.

#### Scenario: Live or fallback Nifty 750 snapshot returned
- GIVEN the universe source is queried
- WHEN live NSE data is reachable or unavailable
- THEN constituents carry ticker, company name, sector and blocklist status
- AND `origin` reports `"live"` or `"bundled"` transparently

### Requirement: 14-sector Relative Rotation Graph (RRG) computation
`GET /discovery/sectors` MUST compute Relative Strength (`rs_ratio`) and RS-Momentum (`rs_momentum`) with 4-week trails across the 14 NSE sector indices relative to Nifty 50 or Nifty 500, assigning each sector to `leading`, `weakening`, `lagging`, or `improving`.

#### Scenario: Sectors placed in four quadrants with history trail
- GIVEN benchmark and sector index histories
- WHEN sector rotation is computed
- THEN each sector returns current `rs_ratio`, `rs_momentum`, quadrant, and weekly trail points

### Requirement: Discovery scan ranks by a single named strategy
A discovery scan (`POST /discovery/scan`, persisted to `scan_runs` and `scan_entries`) MUST evaluate eligible stocks across all four independent strategies and MUST order candidates by one named strategy (`ranked_by`) — never by an average, count, or blended score across strategies.

#### Scenario: Single-strategy ranking attribute preserved
- GIVEN a completed discovery scan over Nifty 750
- WHEN candidates are listed and filtered
- THEN each entry carries all four strategy verdicts independently
- AND ordering uses `ranked_by` and `ranked_conviction` from that single named strategy

#### Scenario: Scheduled post-close scan runs at 16:15 IST
- GIVEN `SCHEDULER_ENABLED=true`
- WHEN the scheduler registers jobs
- THEN a daily Nifty 750 discovery scan is scheduled at `SCAN_RUN_HOUR:SCAN_RUN_MINUTE` IST (default `16:15` IST)

### Requirement: Fundamental quality is a facet, never a silent global gate
Business quality ratios (`roce`, `roe`, `debt_equity`, `sales_growth_3y`, `eps_growth`, `pledge_pct`, `institutional_holding_pct`) fetched via `YFinanceQualitySource` MUST be attached as filterable `QualityReport` facets rather than a universe-wide filter that blocks price-and-volume strategies.

#### Scenario: Price-only strategies still fire when fundamental facets fail
- GIVEN an instrument with weak ROE or unavailable fundamental data
- WHEN the discovery scan runs
- THEN `minervini` and `young_momentum` evaluate price/volume independently
- AND quality facets appear alongside the candidate for interactive filtering

### Requirement: Watchlist persists intent and detects WATCH-to-BUY flips
The watchlist (`GET/POST/PATCH/DELETE /watchlist`) MUST store tracked symbols with `book_intent`, optional `target_strategy_id`, notes, and `last_known_stances`, and MUST compute live distance-to-entry and `WATCH → BUY` flips against the latest scan.

#### Scenario: Flip detected against latest scan
- GIVEN a watched stock whose recorded prior stance in strategy X was `WATCH`
- AND the latest scan produces `BUY` for strategy X
- THEN the watchlist item flags `flipped_buy` naming strategy X

### Requirement: Morning briefing summarizes held exits, watchlist flips, and top buys
`GET /insights/briefing` MUST produce a morning briefing grouping `thesis_broken` / `stop_hit` / `target_hit` alerts, `WATCH → BUY` watchlist flips, top fresh `BUY` candidates with plans, and latest regime & scan context.

#### Scenario: Transition recording emits in-app insights
- GIVEN a completed scan where a held position turns `AVOID` or a watched stock flips `WATCH → BUY`
- WHEN `record_scan_transitions` runs
- THEN corresponding insights are persisted to `insights` for the Today surface

### Requirement: Long-running scans and cycles stream counted-work progress
SSE endpoints (`POST /discovery/scan/stream`, `POST /cycles/run/stream`, `POST /themes/run/stream`) MUST emit honest counted-work progress (`step`, `label`, `completed`, `total`, `elapsed_seconds`) and MUST NOT fabricate a time-based ETA.

#### Scenario: Progress reports actual completed count and elapsed seconds
- GIVEN a streaming discovery scan or agent run
- WHEN progress events arrive
- THEN each event carries `step`, `label`, optional `completed`/`total`, and `elapsed_seconds`
- AND no predicted completion timestamp or synthetic ETA appears

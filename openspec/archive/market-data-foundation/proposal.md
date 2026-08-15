# market-data-foundation

## Intent

Port the predecessor's raw data acquisition behind typed interfaces, so strategies can be
built against a seam that is testable offline — and so no scoring assumption from the old app
arrives with it.

## Why

Every increment after this one needs price history and a list of instruments to reason about.
The predecessor has working plumbing for both, but it is entangled with the things this
rebuild is trying to leave behind: `data/fetcher.py` reads a module-level `config`, bakes
cache TTLs for five intraday intervals into the fetch function, hides the NSE holiday calendar
at the bottom of the same file, and returns bare DataFrames whose shape nothing guarantees.

Porting it as-is would import that entanglement. Rewriting it from nothing would throw away
genuinely hard-won knowledge — which tickers yfinance chokes on, that it returns MultiIndex
columns for a single symbol, that NSE publishes holidays as a yearly PDF nobody can fetch
programmatically. So: same behaviour, new seams.

## In scope

- `app/domain/` — `Instrument`, `PriceSeries` (a validated DataFrame plus provenance)
- `app/data/` protocols — `PriceSource`, `UniverseSource`, `MarketCalendar`
- **Prices** — `YFinancePriceSource` ported from `data/fetcher.py`, **daily and weekly only**
- **Caching** — parquet cache as a separate decorator over any `PriceSource`, not baked in
- **Universe** — NSE index constituents, ported from `data/universe.py`, with the fallback
  list and delisted-ticker blocklist moved out of Python into data files
- **Calendar** — NSE trading days, extracted from the bottom of `data/fetcher.py`, with
  holidays as data and **uncovered years reported rather than silently assumed open**
- `GET /health` reports calendar coverage, so a stale holiday file is visible
- Fixture-backed tests that **never touch the network**, plus a `FakePriceSource` later
  increments can build against

## Out of scope

- **Fundamentals and Screener.in scraping** (`data/fundamentals.py`, 361 lines;
  `longterm/screener_scraper.py`, 738 lines). They are only needed by the quality gates and
  the Fundamental-Technical Momentum strategy, and porting them now would mean speculating
  about a shape those changes have not yet fixed. Deferred to
  `screening-universe-and-gates`.
- **News scraping** (`data/news_scraper.py`) — belongs to the `news_research` skill in
  `skills-registry`, not to the price layer.
- Any scoring, filtering or ranking. `positional/universe.py`'s two-track fundamental filter
  is a *decision*, not plumbing, and is rewritten from spec in a later change.
- Deleting the legacy root packages — still tracked separately.

## Correction: there is no surveillance module

`openspec/project.md`'s roadmap lists `surveillance` among the plumbing to port. There is no
such code. The Supabase `public.surveillance_list` table exists and holds 46 rows, but nothing
in the repository writes to it — it was presumably populated by hand or by code that never
landed. Nothing is being ported because there is nothing to port; surveillance as a *gate*
is specified fresh in `screening-universe-and-gates`.

## Risks

- **yfinance is an unofficial, unstable interface.** It changes shape without notice — hence
  validating at the boundary rather than trusting what comes back.
- **The holiday calendar goes stale every January.** The predecessor's version failed silently
  in that case, treating every weekday as a trading day. Making staleness visible is the
  point of this port, not an extra.

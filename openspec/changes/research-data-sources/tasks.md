# Tasks: research-data-sources

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: market-data (ADDED + MODIFIED), tool-registry (ADDED),
      platform-configuration (ADDED)

## Dependencies
- [x] **`nsepython` evaluated and rejected on evidence.** Its index call is byte-for-byte what
      `requests` with the right headers returns; `nse_eq("TCS")` returns an **empty dict**
      rather than an error on the protected per-stock endpoint; it pulls scipy in for
      arithmetic this module does not do. The header-and-session pattern it exists to supply
      has been in `data/universe.py` since NSE started 403-ing non-browser clients. Installed,
      measured, uninstalled — say the word and it goes back in
- [x] `pdfplumber`, `beautifulsoup4` into a `[data]` extra — not the base install, so a
      checkout without them loses one tool, not the platform

## Quotes — NSE official API
- [x] `app/domain/quotes.py` — `Quote` and `IndexQuote`, deliberately carrying no OHLC
- [x] `app/data/protocols.py` — `QuoteSource` protocol: `quote(instrument) -> Quote | None`
- [x] `app/data/nse_quotes.py` — session bootstrap, browser headers, rate limiter
- [x] Refusal and timeout degrade to empty; nothing raises
- [x] Quote cache; serving cache when the provider is blocked, labelled `cache`
- [x] `^CRSLDX` (Nifty 500) available as `BROAD_BENCHMARK` alongside `^NSEI` — not the
      default, because changing what every RS criterion compares against changes what those
      strategies mean, and that belongs in a change about strategies
- [x] Sector index table widened **8 → 14**, every entry verified against the live NSE index
      list *and* 400 days of provider history before being written
- [x] Assert no strategy and no `PriceSeries` construction path can reach a `QuoteSource`

### Found while building
- [x] **One request returns all 139 indices.** `/api/allIndices` carries level, previous close,
      trailing 30d/365d change, advance/decline breadth, PE, PB and 52-week range for every
      index NSE publishes. The sector view costs a single call, so `discovery-funnel`'s radar
      needs almost no per-index fetching
- [x] **Per-stock quotes are not obtainable this way.** `/api/quote-equity` answers 403 even
      behind a full browser-like session carrying the Akamai cookies its own landing page
      sets — it wants their JS challenge solved. Live per-stock marks must come from the
      broker session (user-present, already authorised) or the last settled close. Recorded in
      the module rather than retried
- [x] Correction to an earlier finding: `^CNXMEDIA`, `^CNXPSUBANK`, `^CNXINFRA` and
      `^CNXCONSUM` are **fine** — 371 bars each. The single-bar reading that condemned them
      was a rate-limit artifact from probing them in a tight loop
- [x] Genuinely unusable: NIFTY HEALTHCARE, OIL & GAS, CONSUMER DURABLES, CHEMICALS and
      CEMENT have no provider ticker returning more than one bar. Live levels readable, no
      relative strength. Recorded in the resource file with instructions to re-verify
- [ ] **`THEMATIC INDICES` — NSE publishes ~40 of them**, including INDIA DEFENCE, RAILWAYS
      PSU, EV & NEW AGE AUTOMOTIVE, INDIA DIGITAL, INDIA MANUFACTURING, MOBILITY. An official,
      maintained theme→constituent mapping, free, in the same payload. Baseline and validation
      set for the theme engine — carried to that change, not built here

## Financials — Indian API
- [x] Captured real responses into `tests/fixtures/indianapi/` — 6 requests, one company,
      `quarter_results`, `balancesheet`, `cashflow`, `ratios`,
      `shareholding_pattern_quarterly`, `/stock`. The model is shaped against these
- [x] `app/data/protocols.py` — `CompanyFinancialsSource`
- [x] `app/domain/financials.py` — metrics, statement series, shareholding; period and
      provider on every figure; derived ratios name their inputs
- [x] `app/data/indian_api.py` — client for `https://stock.indianapi.in`, `X-API-Key`
- [x] `app/data/financials_cache.py` — 30-day document cache, serves expired when starved
- [x] `app/data/provider_budget.py` + migration `0007` — persisted monthly request counter
- [x] Missing key: empty result naming the setting; prices, screening, strategies unaffected
- [x] `QuarterlyFundamentals` untouched — asserted, still exactly four fields
- [x] `/stock_target_price` and `/stock_forecasts` are not called — asserted by a test that
      greps the client source

### The quota reshaped the design
- [x] **`/stock` returns 145 metrics in one request** — ROE, D/E, margins, 3yr and 5yr growth,
      cashflow, plus shareholding, peers and recent news. The whole quality facet costs **one**
      request per company, not the four `/historical_stats` would have. That is the difference
      between 500/month being unworkable and comfortable
- [x] Cache lifetime in **days, not hours** — these figures move four times a year
- [x] Hard budget that **refuses rather than overspends**, counted before the call because a
      request that failed still spent the allowance
- [x] `/historical_stats` kept for genuine long series only, one request per mode, opt-in

### Provider quirks found in real payloads
- [x] **Stray closing parentheses in metric keys** — `returnOnAverageEquityMostRecentFiscalYear)`.
      Raw-key lookups would drop those metrics silently for the companies that carry the typo.
      Keys are normalised
- [x] **`MF` is not `DII`.** The company endpoint reports a mutual-fund row; the shareholding
      endpoint reports all domestic institutions. For one real company they read **5.68 and
      13.41**. Mapping one onto the other would have understated institutional ownership by
      more than half, invisibly. The fields are now separate and `/stock` populates neither
      `dii_pct` nor `public_pct`
- [x] **Peers are provider-internal ids** (`S0003032`), not NSE symbols. Company names are
      stored instead, since an id nothing can resolve is a peer list nothing can use
- [x] **Nulls are real** — interest coverage is null for a debt-free company. Never read as 0
- [x] No quota headers on any response, so the counter is ours to keep

### Not available from this provider
- [x] **No transcripts.** The `/stock` payload contains no transcript, concall, document or PDF
      of any kind, and there is no OpenAPI spec to find another endpoint in. The Screener
      document pipeline is therefore the **whole** commentary capability, not a fallback —
      the two-provider seam stays, with one provider
- [x] **No promoter pledge.** `pledge_pct` stays `None` — "nobody told us", never "none
      pledged". Sourcing it needs exchange filings

## Commentary — seam with two providers
- [x] **Verified: the provider serves no transcripts.** Provider A does not exist. The seam
      stays — it costs nothing and absorbs a second provider later — but the document
      pipeline is the capability
- [x] `app/tools/commentary/` — manifest, handler, provider seam
- [x] ~~Provider A: Indian API transcripts~~ — not available
- [x] Provider B: document pipeline — locate PDF, prefer the exchange-hosted URL when the link
      resolves to one, download with rate limit and identifying user agent
- [x] Serving provider recorded on every document (`exchange` / `aggregator`)
- [x] Cache by source URL hash; a document downloads once
- [x] Ordered, addressable sections split on paragraph boundaries, bounded by size
- [x] Unreadable document reports the failure with its URL; no partial text
- [x] Registered in `ToolRegistry`; evidence-shaped items carrying `source_ref` with a
      `#section=` anchor
- [x] `RateLimiter` extracted to `app/core/` — two callers now, both free services this
      platform reads without an agreement, both blocked for asking too often
- [x] **Verified live**: located a real TCS transcript, resolved to the BSE-hosted copy,
      extracted 9 sections from the actual PDF

## Configuration
- [x] `INDIAN_API_KEY`, `INDIAN_API_MONTHLY_REQUEST_LIMIT`, `FINANCIALS_CACHE_DAYS`,
      `NSE_MIN_REQUEST_INTERVAL_SECONDS`, `NSE_QUOTE_CACHE_SECONDS` — all typed and bounded
- [ ] Health reports each data provider as configured or not, naming the setting
- [ ] No credential value in any response — assert it
- [ ] `project.md` config inventory and data-sources table

## Tests — 863 passing, ruff clean
- [x] A quote carries price, observation time and provider
- [x] Index quote returns level and previous close
- [x] Blocked provider: empty, logged, no raise
- [x] Blocked provider with cache: cached value, labelled cached
- [x] Rate limiter spaces a burst
- [x] **A strategy's series contains no quote-derived bar**
- [ ] **Recomputing a verdict after a quote change leaves it unchanged**
- [x] Financials newest-first; every figure carries period and provider
- [x] Derived ratio names its inputs
- [x] Missing financials are empty, never zero
- [x] Missing API key leaves screening and strategies working
- [x] Shareholding carries its quarter; zero pledge distinguishable from unreported
- [x] Cached financials inside TTL make no provider call
- [x] Commentary returns text, date and URL; absent document is empty not an error
- [x] Commentary sections are ordered, bounded and individually retrievable
- [x] A document is downloaded once
- [x] ~~A covered company uses the API provider~~ — no API provider exists
- [x] The serving provider is recorded on every document
- [x] **No evidence row can cite commentary as a measured value**
- [ ] **No plan level derives from a vendor target; no evidence row cites one**
- [x] All provider clients are injectable and every test runs offline

## Docs
- [ ] `project.md` — data sources table, the history/quote split and why
- [ ] `README.md` — configuration table gains the new keys

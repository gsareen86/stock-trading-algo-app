# research-data-sources

## Intent

Add the three data sources the platform's research actually needs — official NSE quotes,
company financials with shareholding, and management commentary — each behind its own seam.

## Why

The platform reads prices well and knows almost nothing else. Fundamentals are **four fields
wide** by deliberate decision (`market-data-foundation` deferred them; `fun_tech_momentum`
fixed the shape at quarterly EPS and revenue). That was right at the time and is now the
constraint that blocks everything else:

* There is no ROE, ROCE, debt, cashflow or margin anywhere, so a quality filter cannot be
  written — the "is this a good business" question has no data behind it.
* There is no shareholding data, so promoter holding and pledge — the governance facts most
  worth gating on in Indian markets — cannot be checked at all.
* There is no NIFTY 500 index. The platform tracks exactly one benchmark, `^NSEI`.
* Management commentary is absent entirely, and it is where the forward-looking part of a
  thesis actually lives.

`discovery-funnel` cannot be built on top of what exists today. This change is its foundation.

## In scope

**Quotes and index levels — `nsepython`, against NSE's own APIs**

Live quotes, official index levels including NIFTY 500 and the full sector set, and the option
chain. This is the *official* source, so it settles the parity question: what the platform
prints is what NSE printed.

**It does not replace yfinance, and the split is deliberate.** Strategies need 400–800 daily
bars per name across ~500 names. Asking NSE's own endpoints for that is precisely the access
pattern that gets an IP blocked — the caveat that comes attached to this library. So:

| Question | Source |
|---|---|
| Bulk daily and weekly history | yfinance, cached to parquet (unchanged) |
| Live quote, official index level, option chain | nsepython |

**Financials, ratios and shareholding — Indian API, free tier**

Base URL `https://stock.indianapi.in`, authenticated with an `X-API-Key` header. Financial
history is one endpoint with a mode parameter:

```
GET /historical_stats?stock_name=<name>&stats=<mode>
     stats ∈ quarter_results | balancesheet | cashflow | ratios
             shareholding_pattern_quarterly | shareholding_pattern_yearly
```

One endpoint and six modes maps cleanly onto one client and one seam. This arrives behind a
**new** seam rather than by widening the existing four-field one: `fun_tech_momentum` depends
on that narrowness, and a strategy should not acquire twenty optional fields because a screen
wanted four of them.

**Management commentary — provider seam, Indian API preferred**

The same provider publishes conference-call transcripts alongside corporate actions, credit
ratings and annual reports. If that endpoint delivers, it is strictly better than scraping:
licensed, structured, no HTML to break, and no third-party terms to weigh.

So commentary is defined as a **seam with two implementations** — the API first, the Screener
document pipeline (locate PDF → download → extract text) as the fallback for companies the API
does not cover. Which one served a document is recorded on the document.

The exact transcript endpoint is not in the public documentation reachable without a key, so
**the API implementation is written against a verified live response, not against this
proposal.** If it does not exist or does not cover Indian mid-caps adequately, the fallback is
the whole capability and the seam absorbs that without anything else changing.

## Out of scope

- **Replacing yfinance.** It is the history source and stays. It is also correct: `^NSEI` and
  `^CRSLDX` both match the exchange's published closes exactly.
- **Any new strategy.** This change adds data. What reads it arrives with `discovery-funnel`.
- **Sentiment scoring on transcripts.** Same rule `news_research` already follows: return the
  document, never a score. A stored score is untraceable and unversioned, and re-running it
  against a better model silently rewrites history.
- **Intraday.** Live quotes mark positions and drive the market panel. No bar series is built
  from them, and no strategy reads one.
- **Paid tiers.** Everything here works on a free key or no key. A missing key degrades one
  capability and nothing else.
- **Analyst targets and forecasts.** The provider offers `/stock_target_price` and
  `/stock_forecasts`. They are somebody else's opinion, and `discovery-funnel` derives entry,
  stop and target from the strategy that produced the verdict, with every level citing an
  evidence row from that same verdict. An analyst consensus has no such derivation, so it can
  never become a plan level. If it is surfaced later it is research — quoted and attributed,
  like a headline.
- **The provider's own market screens.** `/price_shockers`, `/NSE_most_active` and
  `/fetch_52_week_high_low_data` overlap `discovery-funnel`'s movers. That change requires each
  mover to carry the measurement and the declared threshold that selected it, and a vendor
  screen's methodology is not declared — so movers stay computed here. These endpoints are a
  cross-check, not a source.

## Risks

- **NSE blocks non-browser clients**, which the universe fetcher already handles and already
  documents. Rate limiting, session cookies and a browser user-agent are requirements here, not
  implementation details — and a block must degrade to cache, never raise.
- **A free API tier will rate-limit.** Financials change quarterly; the cache TTL is days, and
  a throttled response serves cache rather than failing a scan.
- **Scraping a third-party page is brittle by construction** and it is the operator's call to
  make. It is confined to one tool, cached per document so a PDF is fetched once, rate-limited,
  and it resolves to the exchange-hosted primary URL when the link points there — which is both
  more durable and less load on Screener.
- **Transcripts are long.** A 40-page PDF does not fit a 12B local model's context. The tool
  returns addressable sections, not one blob, or the capability is unusable on the hardware
  this platform is designed to run on.

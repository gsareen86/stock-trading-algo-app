# Design: research-data-sources

## Four seams, four questions

Every source here answers exactly one question and is reachable only through the seam for that
question. The failure this avoids is the predecessor's: one "data" module that fetched
everything, so no caller could be tested without all of it, and no provider could be swapped
without touching all of it.

| Seam | Question | Provider | Fails to |
|---|---|---|---|
| `PriceSource` | what did it trade at, historically | yfinance + parquet cache | stale cache, then empty |
| `QuoteSource` | what is it trading at now | nsepython | cache, then empty |
| `CompanyFinancialsSource` | what kind of business is it | Indian API | cache, then empty |
| `commentary` tool | what did management say | Screener → exchange PDF | empty, reported |

## Why nsepython does not replace yfinance

It is tempting, because nsepython is the *official* source and settles every parity argument.
The measured facts say otherwise:

```
^NSEI    24078.30  19-Aug-2026    NSE published 24078.30
^CRSLDX  23386.20  19-Aug-2026    NSE published 23386.20
```

yfinance already agrees with the exchange to the paisa, and it serves 400–800 bars per name
across ~500 names from one cached parquet file each. NSE's own endpoints are not built for
that access pattern, and the library's own documented caveat is that they will block an IP that
tries. Swapping the bulk history path to nsepython would trade a working, correct, cached
source for a blocked one.

So the split is by *question*, not by preference: history stays where it works, and nsepython
brings the things yfinance genuinely cannot — the official live level, the full sector index
set, and NIFTY 500 as a first-class benchmark.

## The live-quote boundary is load-bearing

Principle 5 says verdicts are deterministic and reproducible with the LLM off. A live quote
silently entering a price series would break something subtler and worse: the same verdict,
recomputed a minute later, would differ — and nothing would say why.

So a quote is never appended to a series, never substituted for a bar, and never read by a
strategy. Quotes mark positions, drive the market panel and timestamp freshness. Two scenarios
in the delta assert it, because this is the kind of shortcut that gets taken later by someone
who wants a fresher chart.

## Why financials get a new seam instead of a wider old one

`QuarterlyFundamentals` is four fields wide and its docstring explains why: `fun_tech_momentum`
needs quarterly EPS and revenue and nothing else, and the module exists specifically so that
old scoring assumptions were not smuggled into a new strategy.

Widening it to carry ROCE, debt, cashflow and shareholding would put twenty optional fields in
front of the one strategy that reads it, and every one of them would be `None` most of the
time. `CompanyFinancialsSource` is separate, and `fun_tech_momentum` never learns it exists.

## Ratios: received or derived, never ambiguous

The provider supplies some ratios and not others. A ratio the platform computed must be
distinguishable from one it was handed — otherwise a wrong figure cannot be traced to whether
the input or the arithmetic was wrong. Derived ratios name their inputs, in keeping with how
`Evidence` already works.

Sector matters here too: debt-to-equity is a meaningful discriminator for a manufacturer and
nearly meaningless for a bank, and the NIFTY 500 is heavily financial. Any filter built on
these figures — in `discovery-funnel`, not here — has to be sector-aware or it will
systematically exclude the largest sector in the index.

## Transcripts are research, and the distinction is not cosmetic

`agent-graph` already requires that research produces context, never evidence. A transcript is
the strongest possible temptation to break that rule: it contains numbers, management states
them confidently, and they look exactly like measurements.

They are not. A measurement has a threshold, a comparison and a re-fetchable source. Guidance
in a transcript has a speaker. So commentary can be quoted, attributed and read — and can never
become an `Evidence` row or move a `conviction`. Two scenarios assert it.

## Sections, because 40 pages do not fit

A transcript runs 30–60 pages. `gemma4:12b` on consumer hardware cannot take that in one call,
and the platform's default routing is local. Returning one blob would produce a tool that is
correct in tests and unusable in practice.

Sections are ordered, individually addressable and bounded to a configured size, so the caller
retrieves the two that matter rather than the forty that do not.

## Politeness, and the more durable path

The aggregator scrape is confined to one tool, rate-bounded, identified in its user agent, and
cached per document URL so any PDF is downloaded exactly once.

It also resolves past the aggregator where it can: many of the documents Screener lists are
hosted by BSE or NSE, and following the link to its origin is both more durable — an
aggregator's markup changes, an exchange's document URL does not — and less load on a free
service. Where a document exists only on the aggregator, it is fetched from there.

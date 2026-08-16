# remaining-three-strategies

## Intent

Add the other three strategies, so the platform's central claim — four independent verdicts,
never blended — is demonstrable rather than described.

## Why

`verdict-model-and-minervini` proved the decision model against one strategy. One is not a
test of independence: with a single verdict there is nothing to blend, so nothing stops a
future change from quietly reintroducing a composite. Three more strategies, disagreeing on
the same ticker, is what makes the rule visible and what a regression would break.

They also exercise the model in ways Minervini did not. Minervini reads one daily price series;
these need a weekly series, a sector index, a market index and quarterly fundamentals. If the
`Evidence` model only fits price-derived criteria, this is where that shows.

## In scope

- **`FundamentalsSource`** — a deliberately narrow seam: quarterly EPS and revenue only.
  yfinance implementation, plus fake and static ones for offline tests.
- **Sector resources** — the yfinance-sector-string → NSE-sector-index map and the eight index
  tickers, lifted from the predecessor into data files.
- **New indicators** — weekly resampling, multi-year range breakout, consolidation tightness,
  impulse-leg detection, Fibonacci retracement levels.
- **Three strategies**, each emitting evidence per criterion and its own conviction:
  - **`brahma_vishnu_mahesh`** — weekly market regime, sector relative strength, multi-year
    base breakout on volume expansion
  - **`fun_tech_momentum`** — CANSLIM-style earnings/sales surprise, then a tight base near
    highs breaking out on volume
  - **`young_momentum`** — the 1-2-3-4 continuation: base breakout, impulse leg, shallow
    pause, entry trigger

## Out of scope

- **The full fundamentals port.** `data/fundamentals.py` is 361 lines of scoring, bucketing
  and Screener.in URLs. Only the quarterly series is taken; the quality *scoring* is a decision
  and gets rewritten from spec in `screening-universe-and-gates`.
- **Cross-strategy anything.** No agreement score, no ranking, no "3 of 4 agree" field. That is
  the whole point.
- **Narratives** — still `verdict-narratives`.

## The deferral paying off

`market-data-foundation` deferred fundamentals because "porting them now would mean
speculating about a shape those changes have not yet fixed". That shape is now fixed by an
actual consumer: Fun-Tech needs quarterly EPS and revenue, most-recent-first, and nothing else.
So the seam added here is four fields wide instead of a 361-line port of code nobody had a
caller for.

## Risks

- **Three strategies at once is where copy-paste enters.** Each has genuinely different
  criteria; shared mechanics go in `indicators.py`, and anything that looks like a fourth
  strategy's logic living in a third strategy's file is a mistake to catch in review.
- **Fundamentals and sector indices need hosts this environment blocks.** Both seams are
  injectable and tested against hand-built data; live verification is still unavailable here.

# Design: market-data-foundation

## 1. Validate at the boundary, keep pandas inside

Strategies want pandas — VCP contraction detection, rolling relative strength and Trend
Template are all window functions over a DataFrame, and re-expressing them over a list of
typed `Candle` objects would be slower and much harder to read.

But a bare DataFrame guarantees nothing. `data/fetcher.py` returns whatever yfinance produced,
and callers each re-check for emptiness, MultiIndex columns and missing columns — or forget to.

So the seam carries `PriceSeries`: a frozen wrapper holding a DataFrame whose schema has
already been checked, plus the provenance needed to reason about it.

```python
PriceSeries:
    instrument: Instrument
    interval:   Literal["1d", "1wk"]
    frame:      pd.DataFrame   # guaranteed: open/high/low/close/volume, UTC index, sorted
    fetched_at: datetime
    source:     str            # "yfinance" | "cache" | "fake"
```

Construction goes through a validator that lowercases columns, flattens the MultiIndex
yfinance returns for single symbols, drops incomplete rows, sorts the index and rejects a
frame missing any required column. Every strategy then starts from the same guarantees
instead of re-deriving them, and `source` makes "did this come from cache?" answerable —
which matters the first time a backtest disagrees with a live run.

Columns are lowercased on the way in. yfinance's `Open`/`Close` capitalisation is an artefact
of yfinance, not a property of market data, and letting it set the convention would leak the
provider's shape into every strategy.

## 2. Caching is a decorator, not a feature of the fetcher

`data/fetcher.py` interleaves TTL logic with the download, which makes the fetch untestable
without a filesystem and puts the cache policy in the same place as the HTTP call.

Here, `CachingPriceSource` wraps any `PriceSource` and implements the same protocol:

```
strategy → CachingPriceSource → YFinancePriceSource → yfinance
                              ↘ parquet on disk
```

Two consequences worth the indirection. Tests exercise `YFinancePriceSource` with no cache and
the cache with a fake source, so neither test needs the other to work. And the daily/weekly TTL
policy lives in exactly one place rather than being a dict consulted mid-download.

**A stale cache entry is used when the fetch fails.** If yfinance is down and a two-day-old
daily bar file exists, returning it with `source="cache"` beats returning nothing — a
strategy can decide staleness is acceptable, but it cannot decide anything with an empty
frame. This is a deliberate change from the predecessor, which discarded the cache on TTL
expiry regardless of whether a refetch was possible.

## 3. No intraday, enforced by the type

The legacy fetcher accepts `1m`, `5m`, `15m`, `30m`, `60m`, `1h`, `1d`. This platform dropped
intraday, and the interval is therefore a `Literal["1d", "1wk"]` rather than a free string.
An intraday interval is not a runtime error to handle gracefully; it is a change nobody has
proposed, and it should not typecheck.

Weekly is included because Brahma-Vishnu-Mahesh evaluates the Nifty on a weekly chart and
scans multi-year bases — resampling that from daily bars every scan would be wasteful, and
yfinance serves `1wk` directly.

## 4. The calendar's staleness is the feature

The predecessor hardcoded a `set` of ISO date strings, warned when the current year was
missing, and then **returned `False` anyway** — meaning every holiday in an uncovered year is
silently a trading day. That is the worst available behaviour: wrong, and quiet about it.

Two changes:

- **Holidays move to `app/data/nse_holidays.json`**, keyed by year. A yearly data update
  should not be a code change, and a data file makes "which years do we know about?" a
  question with an answer.
- **Coverage is explicit.** `NseCalendar.covers(year)` is public, `is_trading_day` raises
  `CalendarNotCovered` for an uncovered year rather than guessing, and `/health` reports the
  covered range. A caller that genuinely wants to proceed without holiday data can catch it;
  what it cannot do is proceed without knowing.

`/health` is the right place for this because it is already the seam report, and a holiday
file that ran out in December is exactly the kind of thing nobody discovers until a Tuesday in
January when the engine trades into a closed market.

## 5. Universe: fallbacks are data

`data/universe.py` carries a ~200-symbol fallback list and a blocked-ticker set inline in
Python. Both are data — they change when NSE changes, not when logic does — and both move to
JSON alongside the holidays.

The blocklist deserves to survive the port intact: it encodes real, expensively-learned
knowledge that certain symbols return persistent 404s or stale zeroes from yfinance. Losing it
would mean rediscovering it through log spam.

The NSE constituent CSV is fetched over HTTP with the fallback used on any failure, and
`UniverseSnapshot` records which path was taken. A universe that silently shrank to the
fallback list is otherwise indistinguishable from a real index change.

## 6. Tests never touch the network

Every test in this change runs offline. yfinance responses are recorded once into
`tests/fixtures/` and replayed; the NSE CSV likewise. Two reasons beyond speed: a suite that
depends on a third-party endpoint fails for reasons unrelated to the code, and market data
changes daily, so any assertion about real fetched values would be non-deterministic by
construction.

`FakePriceSource` ships as part of the change rather than as test-only scaffolding, because
every strategy increment from here needs a deterministic price series to test against, and
each of them inventing its own would guarantee they diverge.

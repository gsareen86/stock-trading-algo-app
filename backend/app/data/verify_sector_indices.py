"""Check that every sector index in `sector_indices.json` has usable price history.

`market-data` requires an index without usable history to be absent rather than present and
unusable. This is the check that rule refers to: run it on a machine that can reach the provider
whenever an index is added or a ticker changes::

    python -m app.data.verify_sector_indices

It fetches each index's daily history and reports how many bars came back. An index with fewer
than ``MIN_BARS`` bars cannot carry the 3- and 6-month relative-strength measurement
Brahma-Vishnu-Mahesh makes, and the command exits non-zero so it can gate a change.
"""

from __future__ import annotations

from app.data.sectors import all_sector_indices, nse_names
from app.data.yfinance_source import YFinancePriceSource

#: Six months of sessions plus the slope window — the least the sector ranking needs.
MIN_BARS = 150
LOOKBACK_DAYS = 400


def verify(source=None) -> list[tuple[str, str, int, bool]]:
    """(key, ticker, bars, usable) for every configured sector index."""
    source = source or YFinancePriceSource()
    rows = []
    for index in all_sector_indices():
        series = source.history(index.as_instrument(), interval="1d", lookback_days=LOOKBACK_DAYS)
        bars = len(series)
        rows.append((index.key, index.ticker, bars, bars >= MIN_BARS))
    return rows


def main() -> int:
    names = nse_names()
    rows = verify()
    width = max(len(names.get(key, key)) for key, *_ in rows)
    for key, ticker, bars, usable in rows:
        mark = "ok  " if usable else "FAIL"
        print(f"{mark}  {names.get(key, key):<{width}}  {ticker:<22} {bars:>4} bars")
    failed = [key for key, _, _, usable in rows if not usable]
    if failed:
        print(f"\n{len(failed)} index(es) without usable history: {', '.join(failed)}. "
              "Remove them from sector_indices.json or correct the ticker.")
        return 1
    print(f"\nall {len(rows)} sector indices have usable history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

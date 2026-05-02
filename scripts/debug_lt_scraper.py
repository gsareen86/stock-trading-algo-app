"""
One-shot diagnostic for the long-term scraper (deeper version).

Usage (from project root, in PowerShell):
    python -m scripts.debug_lt_scraper ABB AUBANK AADHARHFC

For each ticker we now go a layer deeper:
1. Wipe both view caches.
2. Fetch BOTH consolidated and standalone HTML separately, in isolation.
3. Parse each one and print:
     - the column headers exactly as parsed
     - the matched "Sales / Revenue" row (raw aligned values)
     - how many rows the universe filter would see
4. Then run the real ``fetch_company`` (which contains the
   sparse-consolidated retry) and report the final shape so we can confirm
   the retry actually fired and did the right thing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from longterm.screener_scraper import (   # noqa: E402
    fetch_company,
    _cache_path,
    _fetch_html_one,
    _parse_html,
    _revenue_row_count,
    _extract_section_table,
    _parse_data_table,
)


def _wipe_cache(ticker: str) -> None:
    for view in ("consolidated", "standalone"):
        p = _cache_path(ticker, view)
        if p.exists():
            try:
                p.unlink()
                print(f"   - wiped cache: {p.name}")
            except OSError as e:
                print(f"   - WARN: could not wipe {p}: {e}")


def _show_pl_section(ticker: str, view: str) -> None:
    """Fetch a single view, parse the profit-loss section RAW, and print
    headers + every row label so we can see what screener.in is actually
    sending."""
    html = _fetch_html_one(ticker, view)
    if not html:
        print(f"   [{view}] FETCH FAILED (None returned)")
        return

    soup = BeautifulSoup(html, "lxml")
    sec = _extract_section_table(soup, "profit-loss")
    if sec is None:
        print(f"   [{view}] no <section id='profit-loss'> found")
        return

    headers, rows = _parse_data_table(sec)
    print(f"   [{view}] headers ({len(headers)} cols): {headers}")
    print(f"   [{view}] row labels: {list(rows.keys())}")

    # Try to find the same row our parser would
    sales = None
    sales_label = None
    for label, vals in rows.items():
        low = label.lower()
        if "sales" in low or "revenue" in low:
            sales = vals
            sales_label = label
            break
    if sales is None:
        print(f"   [{view}] NO 'Sales' or 'Revenue' row found in P&L")
    else:
        non_null = sum(1 for v in sales if v is not None)
        print(f"   [{view}] matched row '{sales_label}': "
              f"{len(sales)} cells, {non_null} non-null")
        print(f"   [{view}] values: {sales}")

    # Same for cash-flow (so we can see if Cash bucket is OK separately)
    cf_sec = _extract_section_table(soup, "cash-flow")
    cf_headers, cf_rows = _parse_data_table(cf_sec) if cf_sec else ([], {})
    print(f"   [{view}] cash-flow headers ({len(cf_headers)}): {cf_headers}")
    print(f"   [{view}] cash-flow row labels: {list(cf_rows.keys())}")


def _summarise_final(parsed: dict) -> None:
    print(f"   FINAL view        : {parsed.get('view')}")
    rev = parsed.get("revenue_yearly") or []
    rev_with_value = [r for r in rev if r.get("value") is not None]
    print(f"   FINAL revenue rows: {len(rev)} ({len(rev_with_value)} non-null) "
          f"_revenue_row_count={_revenue_row_count(parsed)}")
    for r in rev:
        print(f"     -> {r}")
    warnings = parsed.get("warnings") or []
    if warnings:
        print(f"   FINAL warnings    :")
        for w in warnings:
            print(f"     - {w}")


def main(tickers):
    for t in tickers:
        t = t.upper().strip()
        print(f"\n========================= {t} =========================")
        _wipe_cache(t)

        print("\n-- per-view raw parse --")
        _show_pl_section(t, "consolidated")
        print()
        _show_pl_section(t, "standalone")

        print("\n-- end-to-end fetch_company (with retry) --")
        # Wipe again so fetch_company really re-fetches both views via its
        # own logic; the per-view calls above will have populated the cache.
        _wipe_cache(t)
        parsed = fetch_company(t, force=True)
        _summarise_final(parsed)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = ["ABB", "AUBANK", "AADHARHFC"]
    main(args)

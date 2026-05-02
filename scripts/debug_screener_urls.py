"""
Probe screener.in URL variants to find the one that returns the FULL
standalone P&L (10+ years) for companies whose consolidated view is sparse
or non-contiguous (ABB, AUBANK).

Usage:
    python -m scripts.debug_screener_urls ABB AUBANK

For each ticker, fetches and prints the HTTP status + parsed P&L year-count
for several URL forms. The one that returns the most years of revenue is
the canonical "standalone" URL we should be using.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

from longterm.screener_scraper import (   # noqa: E402
    USER_AGENT,
    _extract_section_table,
    _parse_data_table,
)

SCREENER_BASE = "https://www.screener.in"

# Variants to try, in priority order. Comments below explain the hypothesis.
URL_VARIANTS = [
    # 1. Bare URL — screener defaults to consolidated when available, else
    #    standalone. For companies with sparse consolidated, this MAY still
    #    show the consolidated sparse view; if so, we move on.
    "/company/{T}/",
    # 2. Explicit consolidated — the path we already know works.
    "/company/{T}/consolidated/",
    # 3. Explicit standalone — what we've been trying but seems to 404.
    "/company/{T}/standalone/",
    # 4. Query-param form — some screener pages toggle via query string.
    "/company/{T}/?consolidated=false",
    # 5. Trailing-less variants.
    "/company/{T}",
    "/company/{T}/standalone",
]


def _fetch(url: str) -> tuple:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT,
                     "Accept-Language": "en-US,en;q=0.9"},
            timeout=20,
            allow_redirects=True,
        )
    except Exception as e:
        return (-1, "", str(e), url)
    return (resp.status_code, resp.text, "", resp.url)


def _pl_year_count(html: str) -> tuple:
    if not html:
        return (0, [], "")
    soup = BeautifulSoup(html, "lxml")
    sec = _extract_section_table(soup, "profit-loss")
    if sec is None:
        return (0, [], "no-pl-section")
    headers, rows = _parse_data_table(sec)
    matched_label = None
    matched_vals = None
    for label, vals in rows.items():
        low = label.lower()
        if "sales" in low or "revenue" in low:
            matched_label = label
            matched_vals = vals
            break
    if matched_vals is None:
        return (0, headers, "no-sales-row")
    non_null = sum(1 for v in matched_vals if v is not None)
    return (non_null, headers, matched_label)


def main(tickers):
    for t in tickers:
        t = t.upper().strip()
        print(f"\n========= {t} =========")
        for variant in URL_VARIANTS:
            url = SCREENER_BASE + variant.replace("{T}", t)
            time.sleep(3.0)  # be polite
            status, html, err, final_url = _fetch(url)
            year_count, headers, label = _pl_year_count(html or "")
            tag = "OK " if status == 200 else f"!{status}"
            redirect = "" if final_url == url else f" -> {final_url}"
            print(f"  {tag}  {variant:35s} | "
                  f"len={len(html or '')} | "
                  f"P&L years={year_count} | "
                  f"row='{label}' | headers={headers}{redirect}")
            if err:
                print(f"      ERR: {err}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = ["ABB", "AUBANK"]
    main(args)

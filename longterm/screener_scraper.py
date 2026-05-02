"""
Screener.in HTML scraper for long-term fundamental data.

Why we scrape, instead of an API
--------------------------------
Screener.in does not have a public API. yfinance — which we already use for
short-term fundamentals — does not return:
  * Multi-year (5+) shareholding pattern
  * FII / DII / Promoter / Pledged % split
  * Indian-specific cash-flow statement structure
  * Multi-year ROCE / interest-coverage history

These are the inputs the user explicitly asked for ("at least 1 DII or FII
invested", "good governance", "positive cash flow"). So we scrape the public
company pages on screener.in.

Politeness
----------
1. Disk-cached HTML (default 24h TTL) at cache/screener/<TICKER>_<view>.html
   -> typical run only re-fetches names that changed yesterday.
2. ``MIN_REQUEST_INTERVAL_SEC`` global rate limit between live requests.
3. ``User-Agent`` header set to a real-looking browser string.
4. Treat any HTTP non-200 as a soft miss and back off; never retry > 2 times.
5. We only ever read public, anonymous pages — no login, no scraping any
   gated content.

Parser philosophy
-----------------
The page structure on screener.in uses anchored ``<section id="...">`` blocks,
each containing ``<table class="data-table ...">``. We parse defensively:
  * If a section/table is missing, we return ``None`` for the relevant field
    rather than raising. The quality scorer then assigns neutral points.
  * We never assume column counts -- we read the header row and align by
    position.
  * We strip ``₹``, ``,``, ``%`` and similar before float-parsing.

Returned shape
--------------
``fetch_company(ticker)`` returns a flat dict like::

    {
      "ticker": "RELIANCE",
      "fetched_at": "2026-04-26T10:00:00",
      "url": "https://www.screener.in/company/RELIANCE/consolidated/",
      "view": "consolidated",            # or "standalone" if consolidated 404'd
      # --- Top ratios (point-in-time) ---
      "market_cap_cr": 1820000.0,        # in INR crore
      "pe": 28.4,
      "roe_pct": 8.1,
      "roce_pct": 9.8,
      "debt_equity": 0.41,
      # --- Multi-year P&L (most-recent-first) ---
      "revenue_yearly": [...],           # [{"period":"Mar 2025","value":...}, ...]
      "net_profit_yearly": [...],
      "eps_yearly": [...],
      # --- Cash flow (most-recent-first) ---
      "cfo_yearly": [...],               # operating cash flow
      "cfi_yearly": [...],
      "cff_yearly": [...],
      # --- Multi-year ratios ---
      "roe_yearly": [...],
      "roce_yearly": [...],
      "interest_coverage_yearly": [...], # if computable from P&L
      # --- Shareholding (most-recent-first quarterly) ---
      "shareholding_quarterly": [
          {"period":"Mar 2026", "promoter_pct":50.4, "fii_pct":21.2,
           "dii_pct":18.7, "public_pct":9.7, "pledged_pct":0.0,
           "shareholders": 1234567},
          ...
      ],
      # --- Aux ---
      "warnings": [...],                 # parse warnings (non-fatal)
    }

Missing values are ``None`` (or empty list). Callers must tolerate Nones.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from config import CACHE_DIR

log = logging.getLogger(__name__)


# ---------- Configuration ----------

CACHE_TTL_HOURS = 24
MIN_REQUEST_INTERVAL_SEC = 3.0    # rate-limit between live HTTP requests
REQUEST_TIMEOUT_SEC = 20
MAX_RETRIES = 2

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

SCREENER_BASE = "https://www.screener.in"

# Sub-folder under existing CACHE_DIR
SCREENER_CACHE = Path(CACHE_DIR) / "screener"
SCREENER_CACHE.mkdir(parents=True, exist_ok=True)

# Module-level last-fetch timestamp for global rate limiting.
_last_fetch_ts: float = 0.0


# ---------- HTTP layer ----------


def _polite_sleep() -> None:
    """Block until ``MIN_REQUEST_INTERVAL_SEC`` has passed since last fetch."""
    global _last_fetch_ts
    delta = time.time() - _last_fetch_ts
    if delta < MIN_REQUEST_INTERVAL_SEC:
        time.sleep(MIN_REQUEST_INTERVAL_SEC - delta)


def _cache_path(ticker: str, view: str) -> Path:
    safe = ticker.upper().replace("/", "_").replace("&", "AND")
    return SCREENER_CACHE / f"{safe}_{view}.html"


def _read_cache(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    )
    if age >= timedelta(hours=CACHE_TTL_HOURS):
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        log.debug("cache read failed %s: %s", path, e)
        return None


def _write_cache(path: Path, html: str) -> None:
    try:
        path.write_text(html, encoding="utf-8")
    except OSError as e:
        log.debug("cache write failed %s: %s", path, e)


def _view_to_url(ticker: str, view: str) -> str:
    """Map our internal view name to the actual screener.in URL.

    Screener.in URL conventions (verified empirically against ABB / AUBANK
    on 2026-04-26):

      * Consolidated:   /company/<TICKER>/consolidated/   -> works.
      * Standalone:     /company/<TICKER>/standalone/    -> 404 (does NOT
                        exist as a path). The standalone view is exposed
                        via the ``?consolidated=false`` query parameter on
                        the bare company URL, OR by visiting the bare URL
                        which screener auto-routes to whichever view is
                        more complete. We use the explicit query form so
                        the request is unambiguous.

    Why this matters
    ----------------
    Before this fix, our sparse-consolidated retry was calling
    ``/company/<T>/standalone/`` which always 404'd, so we silently kept
    the sparse consolidated parse. ABB and AUBANK consequently failed the
    "5 years of P&L history" filter even though their standalone view has
    12+ years.
    """
    t = ticker.upper()
    if view == "standalone":
        return f"{SCREENER_BASE}/company/{t}/?consolidated=false"
    # Default: consolidated (or any future view we add as a path segment).
    return f"{SCREENER_BASE}/company/{t}/{view}/"


def _fetch_html(ticker: str, view: str = "consolidated") -> Tuple[Optional[str], str]:
    """Return (html, used_view). Tries consolidated first, falls back to
    standalone if consolidated 404s (banks/financials often only have
    standalone)."""
    global _last_fetch_ts

    for candidate in [view, "standalone"] if view == "consolidated" else [view]:
        html = _fetch_html_one(ticker, candidate)
        if html:
            return html, candidate

    return None, view


def _fetch_html_one(ticker: str, view: str) -> Optional[str]:
    """Fetch one specific view (consolidated XOR standalone). Honours the
    on-disk cache. Returns the HTML string or None on failure / 404."""
    global _last_fetch_ts

    path = _cache_path(ticker, view)
    cached = _read_cache(path)
    if cached:
        return cached

    url = _view_to_url(ticker, view)
    for attempt in range(MAX_RETRIES + 1):
        _polite_sleep()
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
                timeout=REQUEST_TIMEOUT_SEC,
            )
            _last_fetch_ts = time.time()
        except requests.RequestException as e:
            log.warning("screener fetch error %s (%s/%s): %s",
                        ticker, attempt + 1, MAX_RETRIES + 1, e)
            continue

        if resp.status_code == 200 and len(resp.text) > 5000:
            _write_cache(path, resp.text)
            return resp.text
        if resp.status_code == 404:
            return None
        # Throttled / transient error -> back off
        if resp.status_code in (429, 502, 503):
            time.sleep(5 * (attempt + 1))
            continue
        log.debug("screener %s -> HTTP %s", url, resp.status_code)
        break  # any other status: don't retry

    return None


# ---------- Number helpers ----------

# Indian financial statements use crores. Sometimes screener prefixes with ₹ or
# uses comma separators ("1,23,456").
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _to_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace("\xa0", " ")
    if not s or s in ("-", "—", "NA", "N/A"):
        return None
    s = s.replace(",", "").replace("%", "").replace("₹", "").strip()
    # screener uses unicode minus '−' sometimes
    s = s.replace("−", "-")
    m = _NUM_RE.match(s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _percent(s: Optional[str]) -> Optional[float]:
    """Parse '12.3%' -> 12.3. We keep PERCENT-AS-WHOLE (12.3, not 0.123) because
    screener displays it that way and the quality scorer thresholds are
    expressed in the same units."""
    return _to_float(s)


# ---------- Top-ratios block ----------


def _parse_top_ratios(soup: BeautifulSoup) -> Dict[str, Optional[float]]:
    """Parse the company-card "top ratios" list (Market Cap, P/E, ROE, ROCE,
    Debt to equity, Dividend Yield, etc.). On screener.in this is a ``<ul
    id="top-ratios">`` of ``<li>`` items, each with a ``.name`` and a ``.number``
    span (sometimes labeled ``.value`` in older snapshots)."""
    out: Dict[str, Optional[float]] = {
        "market_cap_cr": None, "pe": None, "roe_pct": None, "roce_pct": None,
        "debt_equity": None, "dividend_yield_pct": None, "book_value": None,
        "industry_pe": None, "face_value": None,
    }
    container = soup.select_one("ul#top-ratios") or soup.select_one("div#top-ratios")
    if container is None:
        # fallback: any element with id top-ratios
        container = soup.find(id="top-ratios")
    if container is None:
        return out

    for li in container.select("li"):
        name_el = li.select_one(".name")
        val_el = li.select_one(".number") or li.select_one(".value")
        if not name_el or not val_el:
            continue
        name = name_el.get_text(strip=True).lower()
        val_text = val_el.get_text(" ", strip=True)
        val = _to_float(val_text)
        if val is None:
            continue
        if "market cap" in name:
            out["market_cap_cr"] = val      # already in crore on screener
        elif name.startswith("stock p/e") or name == "p/e":
            out["pe"] = val
        elif name.startswith("roe"):
            out["roe_pct"] = val
        elif name.startswith("roce"):
            out["roce_pct"] = val
        elif "debt" in name and "equity" in name:
            out["debt_equity"] = val
        elif "dividend yield" in name:
            out["dividend_yield_pct"] = val
        elif "book value" in name:
            out["book_value"] = val
        elif "industry p/e" in name:
            out["industry_pe"] = val
        elif "face value" in name:
            out["face_value"] = val
    return out


# ---------- Generic data-table parser ----------


def _parse_data_table(section) -> Tuple[List[str], Dict[str, List[Optional[float]]]]:
    """Parse a screener-style ``<table class="data-table">`` inside a
    ``<section>``. Returns (period_labels, {row_label: [values...]}) where
    ``period_labels`` are the column headers (most-recent-LAST as on screener,
    we'll reverse later) and each row's values are aligned by position.
    """
    table = section.find("table") if section else None
    if table is None:
        return [], {}

    headers: List[str] = []
    thead = table.find("thead")
    header_row = thead.find("tr") if thead else None
    if header_row is None:
        # Some sections put headers in the first <tr> of <tbody>
        first_tr = table.find("tr")
        if first_tr:
            header_row = first_tr
    if header_row:
        cells = header_row.find_all(["th", "td"])
        # First cell is a blank label column; skip it
        headers = [c.get_text(strip=True) for c in cells[1:]]

    rows: Dict[str, List[Optional[float]]] = {}
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        label = cells[0].get_text(" ", strip=True)
        if not label:
            continue
        # Skip the header row if it ended up here (no thead case)
        if cells[0].name == "th" and label.lower() in ("", "particulars"):
            continue
        values = [_to_float(c.get_text(" ", strip=True)) for c in cells[1:]]
        rows[label] = values
    return headers, rows


def _extract_section_table(soup: BeautifulSoup, section_id: str):
    """Locate ``<section id=...>`` (or any tag with that id)."""
    return soup.find(id=section_id)


def _row_to_records(headers: List[str], values: List[Optional[float]]) -> List[Dict]:
    """Pair up column headers with values. Most-recent-last on screener; we
    reverse at the end so callers always see most-recent-first."""
    n = min(len(headers), len(values))
    if n == 0:
        return []
    out = [{"period": headers[i], "value": values[i]} for i in range(n)]
    out.reverse()
    return out


# ---------- Multi-year sections ----------


def _parse_pl_section(soup: BeautifulSoup) -> Dict[str, List[Dict]]:
    sec = _extract_section_table(soup, "profit-loss")
    headers, rows = _parse_data_table(sec)
    out: Dict[str, List[Dict]] = {
        "revenue_yearly": [], "operating_profit_yearly": [],
        "net_profit_yearly": [], "eps_yearly": [],
        "interest_yearly": [], "depreciation_yearly": [],
    }
    if not rows:
        return out

    def find_row(*keys: str) -> Optional[List[Optional[float]]]:
        for label, vals in rows.items():
            low = label.lower()
            if all(k in low for k in keys):
                return vals
        return None

    rev = find_row("sales") or find_row("revenue")
    op = find_row("operating", "profit")
    np = find_row("net", "profit")
    eps = find_row("eps")
    interest = find_row("interest")
    dep = find_row("depreciation")

    out["revenue_yearly"] = _row_to_records(headers, rev or [])
    out["operating_profit_yearly"] = _row_to_records(headers, op or [])
    out["net_profit_yearly"] = _row_to_records(headers, np or [])
    out["eps_yearly"] = _row_to_records(headers, eps or [])
    out["interest_yearly"] = _row_to_records(headers, interest or [])
    out["depreciation_yearly"] = _row_to_records(headers, dep or [])
    return out


def _parse_cashflow_section(soup: BeautifulSoup) -> Dict[str, List[Dict]]:
    sec = _extract_section_table(soup, "cash-flow")
    headers, rows = _parse_data_table(sec)
    out: Dict[str, List[Dict]] = {
        "cfo_yearly": [], "cfi_yearly": [], "cff_yearly": [],
        "net_cash_yearly": [],
    }
    if not rows:
        return out

    def find_row(*keys: str) -> Optional[List[Optional[float]]]:
        for label, vals in rows.items():
            low = label.lower()
            if all(k in low for k in keys):
                return vals
        return None

    cfo = (find_row("cash", "operating") or find_row("operating", "activities")
           or find_row("cash", "from", "operating"))
    cfi = (find_row("cash", "investing") or find_row("investing", "activities"))
    cff = (find_row("cash", "financing") or find_row("financing", "activities"))
    net = find_row("net", "cash", "flow")

    out["cfo_yearly"] = _row_to_records(headers, cfo or [])
    out["cfi_yearly"] = _row_to_records(headers, cfi or [])
    out["cff_yearly"] = _row_to_records(headers, cff or [])
    out["net_cash_yearly"] = _row_to_records(headers, net or [])
    return out


def _parse_ratios_section(soup: BeautifulSoup) -> Dict[str, List[Dict]]:
    sec = _extract_section_table(soup, "ratios")
    headers, rows = _parse_data_table(sec)
    out: Dict[str, List[Dict]] = {
        "roe_yearly": [], "roce_yearly": [],
        "opm_yearly": [], "debtor_days_yearly": [],
    }
    if not rows:
        return out

    def find_row(*keys: str) -> Optional[List[Optional[float]]]:
        for label, vals in rows.items():
            low = label.lower()
            if all(k in low for k in keys):
                return vals
        return None

    roe = find_row("roe")
    roce = find_row("roce")
    opm = find_row("opm")
    dd = find_row("debtor", "days")

    out["roe_yearly"] = _row_to_records(headers, roe or [])
    out["roce_yearly"] = _row_to_records(headers, roce or [])
    out["opm_yearly"] = _row_to_records(headers, opm or [])
    out["debtor_days_yearly"] = _row_to_records(headers, dd or [])
    return out


def _parse_shareholding_section(soup: BeautifulSoup) -> List[Dict]:
    """Return list of quarterly shareholding records, most-recent-first.

    Screener has a tabbed view inside ``<section id="shareholding">``: a
    quarterly tab and a yearly tab. Each tab has its own ``<table>`` and the
    quarterly data is what we want for the "FII/DII increased recently"
    signal. The HTML structure has been stable: a tab container with
    ``data-toggle="tab"`` links and content panes ``id="quarterly-shp"`` /
    ``id="yearly-shp"``.
    """
    section = _extract_section_table(soup, "shareholding")
    if section is None:
        return []

    # Prefer the explicit quarterly pane; fall back to the first table in the
    # section if the markup has changed.
    quarterly_pane = section.find(id="quarterly-shp") or section
    headers, rows = _parse_data_table(quarterly_pane)
    if not headers or not rows:
        return []

    def find_row(*keys: str) -> Optional[List[Optional[float]]]:
        for label, vals in rows.items():
            low = label.lower()
            if all(k in low for k in keys):
                return vals
        return None

    promoters = find_row("promoter")
    fii = find_row("fii") or find_row("foreign")
    dii = find_row("dii") or find_row("domestic")
    govt = find_row("government")
    public = find_row("public")
    pledged = find_row("pledged") or find_row("pledge")
    shareholders = find_row("no. of shareholders") or find_row("shareholders")

    # Screener.in shows the "Pledged %" row only when there IS pledged stock
    # to disclose. When the row is absent, the correct interpretation is
    # "0% pledged", not "data missing". We materialise zeros here so the
    # filter and the dashboard both see a clean 0.0 instead of ``None``,
    # which would render as "—" and look like a parsing failure.
    if promoters and not pledged:
        pledged = [0.0] * len(promoters)

    n_cols = len(headers)
    records: List[Dict] = []
    for i in range(n_cols):
        rec = {
            "period": headers[i],
            "promoter_pct": (promoters[i] if promoters and i < len(promoters) else None),
            "fii_pct":       (fii[i]       if fii       and i < len(fii)       else None),
            "dii_pct":       (dii[i]       if dii       and i < len(dii)       else None),
            "govt_pct":      (govt[i]      if govt      and i < len(govt)      else None),
            "public_pct":    (public[i]    if public    and i < len(public)    else None),
            "pledged_pct":   (pledged[i]   if pledged   and i < len(pledged)   else None),
            "shareholders":  (shareholders[i] if shareholders and i < len(shareholders) else None),
        }
        records.append(rec)
    records.reverse()  # most-recent-first
    return records


# ---------- Public API ----------


def _parse_html(ticker: str, html: str, used_view: str) -> Dict:
    """Run all section parsers on a single HTML page. Returns the flat dict
    that ``fetch_company`` ultimately yields (sans final view-arbitration)."""
    soup = BeautifulSoup(html, "lxml")
    warnings: List[str] = []

    top = _parse_top_ratios(soup)
    if not any(v is not None for v in top.values()):
        warnings.append("top-ratios block missing or empty")

    pl = _parse_pl_section(soup)
    if not pl["revenue_yearly"]:
        warnings.append("profit-loss section missing")

    cf = _parse_cashflow_section(soup)
    if not cf["cfo_yearly"]:
        warnings.append("cash-flow section missing")

    rt = _parse_ratios_section(soup)
    if not rt["roe_yearly"]:
        warnings.append("ratios section missing")

    sh = _parse_shareholding_section(soup)
    if not sh:
        warnings.append("shareholding section missing")

    return {
        "ticker": ticker.upper(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "url": _view_to_url(ticker, used_view),
        "view": used_view,
        **top,
        **pl,
        **cf,
        **rt,
        "shareholding_quarterly": sh,
        "warnings": warnings,
    }


def _revenue_row_count(parsed: Dict) -> int:
    """How many years of revenue data the parsed dict actually carries."""
    rev = parsed.get("revenue_yearly") or []
    return len([r for r in rev if r.get("value") is not None])


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _has_year_gaps(parsed: Dict, max_gap_years: int = 2) -> bool:
    """True if the parsed revenue periods contain a non-contiguous year jump
    larger than ``max_gap_years``.

    Screener.in occasionally serves a sparse-but-numerous consolidated view
    e.g. for ABB: ``['Dec 2011', 'Dec 2012', 'Dec 2024', 'Dec 2025']``.
    Without this check the retry logic only fires when there are < 5 rows;
    a sparse 5+ row view with a 12-year hole would slip through. We treat
    a gap > 2 years as evidence the view is incomplete and worth a retry.
    """
    rev = parsed.get("revenue_yearly") or []
    years: List[int] = []
    for r in rev:
        m = _YEAR_RE.search(str(r.get("period") or ""))
        if m:
            try:
                years.append(int(m.group(0)))
            except ValueError:
                pass
    if len(years) < 2:
        return False
    years.sort()
    for a, b in zip(years, years[1:]):
        if b - a > max_gap_years:
            return True
    return False


def fetch_company(ticker: str, force: bool = False) -> Dict:
    """
    Fetch + parse one company. Network-cached (24h). Returns a flat dict (see
    module docstring). Returns ``{}`` if scraping fails entirely.

    ``force=True`` bypasses the cache and re-fetches.

    View arbitration
    ----------------
    Many Indian-listed companies file consolidated statements only when there
    are subsidiaries to consolidate. If a company is mostly-standalone (e.g.
    ABB India, most banks) screener.in still serves the consolidated URL with
    HTTP 200 but the P&L / Cash-flow tables are sparse (often 1-2 years).
    Falling back only on 404 is therefore not enough. We always parse the
    consolidated view first, and if it has < ``MIN_YEARS_FOR_PRIMARY``
    revenue rows, we additionally fetch standalone and pick whichever view
    carries more data.
    """
    MIN_YEARS_FOR_PRIMARY = 5  # below this, retry standalone

    if force:
        for v in ("consolidated", "standalone"):
            p = _cache_path(ticker, v)
            try:
                p.unlink(missing_ok=True)  # py3.8+
            except (TypeError, OSError):
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass

    html, used_view = _fetch_html(ticker)
    if not html:
        return {}

    parsed = _parse_html(ticker, html, used_view)

    # Sparse-or-gappy-consolidated retry. If we landed on consolidated but
    # the P&L is short OR has multi-year gaps (e.g. ABB: 2011, 2012, 2024,
    # 2025), the company likely files mostly-standalone. Try the standalone
    # view (served on screener.in via ``?consolidated=false``) and keep it
    # if it has more revenue rows.
    needs_retry = used_view == "consolidated" and (
        _revenue_row_count(parsed) < MIN_YEARS_FOR_PRIMARY
        or _has_year_gaps(parsed)
    )
    if needs_retry:
        alt_html = _fetch_html_one(ticker, "standalone")
        if alt_html:
            alt_parsed = _parse_html(ticker, alt_html, "standalone")
            if _revenue_row_count(alt_parsed) > _revenue_row_count(parsed):
                parsed = alt_parsed
                parsed.setdefault("warnings", []).append(
                    "fell back to standalone (consolidated was sparse or gappy)"
                )

    return parsed


def latest_shareholding(parsed: Dict) -> Dict:
    """Convenience accessor: most-recent quarter's shareholding row, or {}."""
    sh = parsed.get("shareholding_quarterly") or []
    return sh[0] if sh else {}


def shareholding_qoq_change(parsed: Dict, key: str) -> Optional[float]:
    """Latest minus previous quarter for `key` (e.g. 'fii_pct'). Returns None
    if not enough data."""
    sh = parsed.get("shareholding_quarterly") or []
    if len(sh) < 2:
        return None
    a, b = sh[0].get(key), sh[1].get(key)
    if a is None or b is None:
        return None
    return float(a - b)


def to_lt_universe_row(parsed: Dict) -> Dict:
    """Project the parsed scraper dict down to a flat row matching the
    ``lt_universe`` table schema. Used by the universe builder.
    """
    latest = latest_shareholding(parsed)
    return {
        "ticker": parsed.get("ticker"),
        "last_filtered_at": datetime.now(timezone.utc).isoformat(),
        "market_cap": parsed.get("market_cap_cr"),  # already in crore
        "sector": None,           # screener doesn't expose a clean sector tag;
        "industry": None,         # we'll fill these from yfinance later if needed
        "fii_pct": latest.get("fii_pct"),
        "dii_pct": latest.get("dii_pct"),
        "fii_qoq_change": shareholding_qoq_change(parsed, "fii_pct"),
        "dii_qoq_change": shareholding_qoq_change(parsed, "dii_pct"),
        "promoter_holding_pct": latest.get("promoter_pct"),
        "promoter_pledge_pct": latest.get("pledged_pct"),
        "has_fii": 1 if (latest.get("fii_pct") or 0) > 0 else 0,
        "has_dii": 1 if (latest.get("dii_pct") or 0) > 0 else 0,
        "in_universe": 0,         # filled by universe builder
        "filter_reason": None,
        "raw_inputs": json.dumps({
            "url": parsed.get("url"),
            "view": parsed.get("view"),
            "warnings": parsed.get("warnings"),
            "shareholding_recent": (parsed.get("shareholding_quarterly") or [])[:4],
        }, default=str),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    d = fetch_company(t)
    print(f"--- {t} ---")
    for k, v in d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            print(f"{k}: {len(v)} rows; first={v[0]}")
        else:
            print(f"{k}: {v}")

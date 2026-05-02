"""
Long-term universe builder.

Applies the user's hard filters on top of the NIFTY 500 list to produce
a *candidate* universe. The output is upserted into the ``lt_universe``
table so the quality scorer (longterm/quality.py) only has to score names
that survived these gates.

Hard filters (any failure -> excluded)
--------------------------------------
1. Market cap >= MIN_MARKET_CAP_CR (default 1000 crore)
2. At least ONE of FII or DII has a position (>= MIN_INSTITUTIONAL_PCT)
3. Promoter pledge <= MAX_PROMOTER_PLEDGE_PCT (50% per user spec)
4. Has at least 5 years of P&L history (rough governance/maturity gate)

We deliberately keep these filters *generous* on Phase A. The 5-bucket
quality scorer (Phase A's next module) does the bulk of the discrimination
on a 0-100 scale, and the universe rebuilder runs weekly while the scorer
runs daily.

Why not use yfinance market cap?
--------------------------------
yfinance's market cap is in absolute INR (~10^13). Screener.in shows it in
crores already (e.g. 18,20,000 cr). We use the screener number as the
canonical source so the dashboard and the filter agree byte-for-byte.

Failure handling
----------------
If a ticker fails to scrape (404, timeout, parse error), we record it in
``lt_universe`` with ``in_universe=0`` and ``filter_reason='scrape_failed'``
so the dashboard can surface coverage gaps without the run aborting.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from data.universe import load_universe
from db.models import get_conn
from longterm.screener_scraper import (
    fetch_company,
    latest_shareholding,
    shareholding_qoq_change,
)

# `data.fundamentals` is imported lazily inside `_get_industry` to keep
# the universe module loadable in environments where yfinance is broken
# / sandboxed; the function-level import is cheap on subsequent calls.

log = logging.getLogger(__name__)


# ---------- Hard-filter thresholds ----------

MIN_MARKET_CAP_CR = 1_000.0          # user requirement: >= 1000 crore
MIN_INSTITUTIONAL_PCT = 0.5          # accept if FII or DII >= 0.5%
MAX_PROMOTER_PLEDGE_PCT = 50.0       # user requirement
MIN_YEARS_HISTORY = 5                # need 5+ years of P&L for the scorer


# ---------- Filter logic ----------


def _evaluate_filters(parsed: Dict) -> Dict[str, object]:
    """Run all hard filters on a parsed scraper dict. Returns a dict with:
        - passed:       bool (overall)
        - reasons:      list of human-readable failure reasons (empty if passed)
        - market_cap:   the resolved market cap (crore)
        - institutional_present: bool
        - pledge_pct:   the latest pledge %
    """
    reasons: List[str] = []

    mcap = parsed.get("market_cap_cr")
    if mcap is None:
        reasons.append("market_cap_missing")
    elif mcap < MIN_MARKET_CAP_CR:
        reasons.append(f"mcap_below_{int(MIN_MARKET_CAP_CR)}cr")

    latest = latest_shareholding(parsed)
    fii = latest.get("fii_pct") or 0.0
    dii = latest.get("dii_pct") or 0.0
    institutional_present = (fii >= MIN_INSTITUTIONAL_PCT
                             or dii >= MIN_INSTITUTIONAL_PCT)
    if not institutional_present:
        reasons.append("no_institutional_holding")

    pledge = latest.get("pledged_pct")
    if pledge is not None and pledge > MAX_PROMOTER_PLEDGE_PCT:
        reasons.append(f"pledge_above_{int(MAX_PROMOTER_PLEDGE_PCT)}pct")

    rev_years = parsed.get("revenue_yearly") or []
    if len([r for r in rev_years if r.get("value") is not None]) < MIN_YEARS_HISTORY:
        reasons.append(f"insufficient_history_under_{MIN_YEARS_HISTORY}y")

    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "market_cap": mcap,
        "institutional_present": institutional_present,
        "pledge_pct": pledge,
    }


# ---------- yfinance industry/sector lookup ----------


def _get_industry_sector(ticker: str) -> tuple:
    """Return (sector, industry) for a ticker, using ``data.fundamentals``
    which itself caches in the ``fundamentals`` table for 24h. Returns
    ``(None, None)`` if yfinance is unavailable or the ticker is unknown.

    This is the bridge that lets the long-term Cash-Quality scorer detect
    banks / HFCs / NBFCs without needing its own yfinance call. Keeping the
    lookup here (in the universe builder, run weekly) means the scorer
    (run daily) just reads it back from ``lt_universe``.
    """
    try:
        from data.fundamentals import fetch_and_store as _fs
    except Exception as e:
        log.debug("data.fundamentals import failed: %s", e)
        return (None, None)

    try:
        row = _fs(ticker) or {}
    except Exception as e:
        log.debug("fetch_and_store failed for %s: %s", ticker, e)
        return (None, None)
    return (row.get("sector") or None, row.get("industry") or None)


# ---------- Persistence ----------


_UPSERT_SQL = """
INSERT INTO lt_universe (
    ticker, last_filtered_at, market_cap, sector, industry,
    has_fii, has_dii, fii_pct, dii_pct, fii_qoq_change, dii_qoq_change,
    promoter_holding_pct, promoter_pledge_pct,
    in_universe, filter_reason, raw_inputs
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT (ticker) DO UPDATE SET
    last_filtered_at      = EXCLUDED.last_filtered_at,
    market_cap            = EXCLUDED.market_cap,
    sector                = EXCLUDED.sector,
    industry              = EXCLUDED.industry,
    has_fii               = EXCLUDED.has_fii,
    has_dii               = EXCLUDED.has_dii,
    fii_pct               = EXCLUDED.fii_pct,
    dii_pct               = EXCLUDED.dii_pct,
    fii_qoq_change        = EXCLUDED.fii_qoq_change,
    dii_qoq_change        = EXCLUDED.dii_qoq_change,
    promoter_holding_pct  = EXCLUDED.promoter_holding_pct,
    promoter_pledge_pct   = EXCLUDED.promoter_pledge_pct,
    in_universe           = EXCLUDED.in_universe,
    filter_reason         = EXCLUDED.filter_reason,
    raw_inputs            = EXCLUDED.raw_inputs
"""


def _row_for_db(parsed: Dict, verdict: Dict,
                sector: Optional[str] = None,
                industry: Optional[str] = None) -> tuple:
    latest = latest_shareholding(parsed)
    raw = json.dumps({
        "url": parsed.get("url"),
        "view": parsed.get("view"),
        "warnings": parsed.get("warnings"),
        "shareholding_recent": (parsed.get("shareholding_quarterly") or [])[:4],
        "filter_reasons": verdict.get("reasons", []),
        "sector": sector,
        "industry": industry,
    }, default=str)
    return (
        parsed.get("ticker"),
        datetime.now(timezone.utc).isoformat(),
        parsed.get("market_cap_cr"),
        sector,
        industry,
        1 if (latest.get("fii_pct") or 0) > 0 else 0,
        1 if (latest.get("dii_pct") or 0) > 0 else 0,
        latest.get("fii_pct"),
        latest.get("dii_pct"),
        shareholding_qoq_change(parsed, "fii_pct"),
        shareholding_qoq_change(parsed, "dii_pct"),
        latest.get("promoter_pct"),
        latest.get("pledged_pct"),
        1 if verdict["passed"] else 0,
        ",".join(verdict["reasons"]) if verdict["reasons"] else "passed_all_filters",
        raw,
    )


def _record_failure(ticker: str, reason: str) -> None:
    """Record a scrape/parse failure as in_universe=0 row."""
    with get_conn() as conn:
        conn.execute(
            _UPSERT_SQL,
            (
                ticker.upper(),
                datetime.now(timezone.utc).isoformat(),
                None, None, None,
                0, 0, None, None, None, None, None, None,
                0, reason, "{}"
            ),
        )


# ---------- Public API ----------


def filter_one(ticker: str, force: bool = False) -> Optional[Dict]:
    """Scrape + filter one ticker, persist to ``lt_universe``. Returns the
    verdict dict, or ``None`` if scraping failed entirely.

    Side-effect: also fetches sector/industry from yfinance (cached in the
    ``fundamentals`` table) and persists them on the row so the daily
    quality scorer can route banks/HFCs through the loan-book Cash variant
    without paying the yfinance cost itself.
    """
    try:
        parsed = fetch_company(ticker, force=force)
    except Exception as e:
        log.warning("scrape exception for %s: %s", ticker, e)
        _record_failure(ticker, "scrape_exception")
        return None

    if not parsed:
        _record_failure(ticker, "scrape_failed")
        return None

    sector, industry = _get_industry_sector(ticker)

    verdict = _evaluate_filters(parsed)
    with get_conn() as conn:
        conn.execute(
            _UPSERT_SQL,
            _row_for_db(parsed, verdict, sector=sector, industry=industry),
        )
    return verdict


def build_universe(
    tickers: Optional[List[str]] = None,
    limit: Optional[int] = None,
    force: bool = False,
    progress_cb=None,
    skip_existing: bool = False,
) -> Dict[str, int]:
    """
    Build the long-term universe.

    Parameters
    ----------
    tickers : list of NSE codes (without .NS). Defaults to NIFTY 500.
    limit   : optional cap (useful for first-run dry tests).
    force   : if True, bypass the screener.in HTML cache.
    progress_cb : optional ``callable(idx, total, ticker, verdict)`` for the
                  Streamlit dashboard's status bar.
    skip_existing : if True, drop tickers that already have a row in
                  ``lt_universe`` so an interrupted Phase A run can be resumed
                  WITHOUT redoing the work for the first N tickers. The user
                  asked for this after the NIFTY 500 import only made it through
                  333 tickers — they wanted the remaining 167 without
                  re-scraping the first 333.

    Returns counts: ``{"total":N, "passed":P, "failed":F, "errors":E,
                       "skipped":S}``.
    """
    tickers = tickers or load_universe()

    skipped = 0
    if skip_existing:
        try:
            with get_conn() as conn:
                existing = {
                    r["ticker"] for r in conn.execute(
                        "SELECT ticker FROM lt_universe"
                    ).fetchall()
                }
        except Exception as e:
            log.warning("skip_existing: could not read lt_universe (%s); "
                        "falling back to full run", e)
            existing = set()
        before = len(tickers)
        tickers = [t for t in tickers if t not in existing]
        skipped = before - len(tickers)
        log.info("skip_existing: %d tickers already in lt_universe; "
                 "processing remaining %d", skipped, len(tickers))

    if limit:
        tickers = tickers[:limit]

    counts = {"total": len(tickers), "passed": 0, "failed": 0, "errors": 0,
              "skipped": skipped}
    for idx, t in enumerate(tickers, 1):
        try:
            verdict = filter_one(t, force=force)
        except Exception as e:
            log.warning("universe filter exception %s: %s", t, e)
            counts["errors"] += 1
            verdict = None

        if verdict is None:
            counts["errors"] += 1
        elif verdict["passed"]:
            counts["passed"] += 1
        else:
            counts["failed"] += 1

        if progress_cb:
            try:
                progress_cb(idx, len(tickers), t, verdict)
            except Exception:
                pass

        if idx % 25 == 0:
            log.info("universe progress: %d/%d  passed=%d failed=%d errors=%d",
                     idx, len(tickers), counts["passed"], counts["failed"],
                     counts["errors"])
    return counts


def get_universe_rows(passed_only: bool = True) -> list:
    """Read the lt_universe table back as a list of dicts."""
    sql = "SELECT * FROM lt_universe"
    if passed_only:
        sql += " WHERE in_universe = 1"
    sql += " ORDER BY market_cap DESC NULLS LAST"
    # NULLS LAST is Postgres-only; SQLite ignores NULLS LAST and just sorts
    # NULLs FIRST under DESC. Detect backend and adjust.
    try:
        from db.models import BACKEND
        if BACKEND == "sqlite":
            sql = sql.replace(" NULLS LAST", "")
    except ImportError:
        pass
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Quick smoke-test on a tiny slice.
    print(build_universe(limit=5, force=False))

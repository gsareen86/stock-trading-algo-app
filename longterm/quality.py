"""
5-bucket multi-year quality scorer.

This is the heart of the long-term module. It assigns 0-100 points to each
candidate using the inputs scraped by ``longterm.screener_scraper``. The
buckets and their max points sum to 100:

    Profitability   25   ROE / ROCE / net margin / no-loss-years
    Cash quality    20   OCF positive years; OCF/NetProfit ratio
    Solvency        15   Debt/Equity; interest coverage
    Growth          20   Revenue 5y CAGR; EPS 5y CAGR; no negative years
    Governance      20   Promoter holding; pledge; holding stability

Why a rule-based scorer (not ML)?
---------------------------------
- Transparent: every input that contributed to the score is visible in the
  ``raw_inputs`` JSON. The user can audit any rejection or selection.
- Stable: with no ML training set, a hand-tuned rubric is more robust than
  a model fit to opinion. We can layer ML on top later (Phase 2 is already
  designed around that hand-off in config.py).
- Bank-aware: banks have a fundamentally different debt structure
  (deposits = liabilities). We special-case the Solvency bucket for them.

Inputs
------
The scorer takes the *parsed dict* from ``screener_scraper.fetch_company``
plus an optional ``industry`` hint (yfinance/internal classification). If
industry is unknown we conservatively treat the company as non-bank.

Output
------
``score_company(parsed, industry=None)`` returns::

    {
      "ticker": "RELIANCE",
      "scored_at": "2026-04-26T...",
      "profitability_score": 22.0,   # 0-25
      "cash_quality_score":  18.0,   # 0-20
      "solvency_score":      12.0,   # 0-15
      "growth_score":        16.0,   # 0-20
      "governance_score":    18.0,   # 0-20
      "total_score":         86.0,   # 0-100
      "raw_inputs": {...}            # every component value used
    }

Persistence: ``score_and_store`` upserts into ``lt_quality``.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.models import get_conn
from longterm.screener_scraper import fetch_company

log = logging.getLogger(__name__)


# ---------- Generic helpers ----------


def _values_recent_first(records: List[Dict], n: Optional[int] = None) -> List[float]:
    """Pull the numeric ``value`` field from a list of {period, value} records,
    skipping Nones. Records arrive most-recent-first from the scraper.
    """
    out: List[float] = []
    for r in records or []:
        v = r.get("value")
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
        if n is not None and len(out) >= n:
            break
    return out


def _avg(xs: List[float]) -> Optional[float]:
    return (sum(xs) / len(xs)) if xs else None


def _cagr(values_recent_first: List[float], years: int = 5) -> Optional[float]:
    """Compute % CAGR using the most-recent value vs the value `years` ago.
    Returns the result in PERCENTAGE units (e.g. 12.3 for 12.3%)."""
    vals = [v for v in values_recent_first if v and v > 0]
    if len(vals) < 2:
        return None
    end = vals[0]
    start_idx = min(years, len(vals) - 1)
    start = vals[start_idx]
    if start <= 0 or end <= 0 or start_idx <= 0:
        return None
    try:
        return (math.pow(end / start, 1.0 / start_idx) - 1.0) * 100.0
    except (ValueError, ZeroDivisionError):
        return None


def _is_loan_book_business(industry: Optional[str]) -> bool:
    """Detect banks, NBFCs, HFCs and similar lending businesses.

    Why this matters
    ----------------
    Loan-book businesses fund themselves by raising deposits / borrowings and
    deploying that as loans. From a cash-flow statement perspective, every
    rupee of net new loans shows up as a *negative* operating cash flow
    (inventory build-up, in effect). Healthy, *growing* HFCs and banks
    therefore routinely report negative OCF — but high and stable net
    profit. Our generic Cash-Quality scorer would mark them as failing
    ("0 positive CFO years"), which is exactly the AADHARHFC=0 bug.

    yfinance industry strings we want to catch (case-insensitive substring):
      * "Banks - ..."             (Banks - Regional / Diversified)
      * "Credit Services"         (some NBFCs / consumer-finance)
      * "Mortgage Finance"        (some HFCs)
      * "Housing Finance"         (Indian listed HFCs sometimes get this)
      * "Capital Markets"         is intentionally NOT here — brokers /
                                  exchanges are not loan-book businesses.

    We err on the side of being inclusive — a false positive only changes
    the Cash bucket scoring rule for one company, never excludes them.
    """
    if not industry:
        return False
    i = industry.lower()
    keywords = (
        "bank",
        "credit services",
        "housing finance",
        "mortgage",
        "consumer finance",
        "nbfc",
        "non-banking",
        "asset management",  # some AMCs misclassified, harmless if mis-flag
    )
    return any(k in i for k in keywords)


# Backwards-compat alias kept for older imports.
_bank_like = _is_loan_book_business


# ---------- Bucket 1: Profitability (max 25) ----------


def _score_profitability(parsed: Dict, raw_out: Dict) -> float:
    """
    Components (out of 25):
      - 5y avg ROE       (0..8)
      - 5y avg ROCE      (0..8)
      - 5y avg net margin (0..5)
      - No loss years in last 5  (0 or 4)
    """
    pts = 0.0

    roe5 = _avg(_values_recent_first(parsed.get("roe_yearly"), n=5))
    raw_out["roe_5y_avg"] = roe5
    if roe5 is not None:
        if roe5 >= 20:
            pts += 8
        elif roe5 >= 15:
            pts += 6
        elif roe5 >= 12:
            pts += 4
        elif roe5 >= 8:
            pts += 2

    roce5 = _avg(_values_recent_first(parsed.get("roce_yearly"), n=5))
    raw_out["roce_5y_avg"] = roce5
    if roce5 is not None:
        if roce5 >= 20:
            pts += 8
        elif roce5 >= 15:
            pts += 6
        elif roce5 >= 12:
            pts += 4
        elif roce5 >= 8:
            pts += 2

    # Net margin: derive from net profit / revenue when both present
    rev = _values_recent_first(parsed.get("revenue_yearly"), n=5)
    npft = _values_recent_first(parsed.get("net_profit_yearly"), n=5)
    margins: List[float] = []
    for r, n in zip(rev, npft):
        if r and r > 0:
            margins.append((n / r) * 100.0)
    nm5 = _avg(margins)
    raw_out["net_margin_5y_avg_pct"] = nm5
    if nm5 is not None:
        if nm5 >= 15:
            pts += 5
        elif nm5 >= 10:
            pts += 4
        elif nm5 >= 5:
            pts += 2
        elif nm5 > 0:
            pts += 1

    # No-loss-years bonus (scope: last 5 years)
    npft5 = _values_recent_first(parsed.get("net_profit_yearly"), n=5)
    raw_out["loss_years_in_last_5"] = (
        sum(1 for v in npft5 if v < 0) if npft5 else None
    )
    if npft5 and len(npft5) >= 3 and all(v > 0 for v in npft5):
        pts += 4

    return min(pts, 25.0)


# ---------- Bucket 2: Cash quality (max 20) ----------


def _score_cash_quality(parsed: Dict, raw_out: Dict,
                        is_loan_book: bool = False) -> float:
    """
    Non-loan-book companies (out of 20):
      - Years with positive operating cash flow in last 5 (0..10)
      - Avg OCF / Net Profit ratio over last 5 years      (0..10)
        Healthy >= 0.8; signals real earnings, not accruals.

    Loan-book businesses (banks / HFCs / NBFCs) — out of 20:
      Operating cash flow is structurally negative for any healthy, growing
      lender (every rupee of new loans = negative CFO). Penalising that
      makes no sense, so we substitute earnings-quality proxies that
      genuinely signal cash health for a loan book:
        - Years with positive NET PROFIT in last 5            (0..10)
        - Years with NET PROFIT growth YoY in last 5          (0..6)
        - Net-profit smoothing: stddev / mean ratio in last 5 (0..4)
            (lower volatility = higher quality earnings)

    The two paths sum to the same 0..20 cap so the total stays comparable
    across the universe.
    """
    if is_loan_book:
        return _score_cash_quality_loan_book(parsed, raw_out)

    pts = 0.0

    cfo5 = _values_recent_first(parsed.get("cfo_yearly"), n=5)
    pos_years = sum(1 for v in cfo5 if v > 0) if cfo5 else 0
    raw_out["positive_cfo_years_in_last_5"] = pos_years
    raw_out["cfo_5y"] = cfo5
    if pos_years >= 5:
        pts += 10
    elif pos_years == 4:
        pts += 7
    elif pos_years == 3:
        pts += 4
    elif pos_years == 2:
        pts += 1

    npft5 = _values_recent_first(parsed.get("net_profit_yearly"), n=5)
    ratios: List[float] = []
    for cfo, npft in zip(cfo5, npft5):
        if npft and npft > 0:
            ratios.append(cfo / npft)
    avg_r = _avg(ratios)
    raw_out["cfo_to_net_profit_5y_avg"] = avg_r
    if avg_r is not None:
        if avg_r >= 1.1:
            pts += 10
        elif avg_r >= 0.9:
            pts += 7
        elif avg_r >= 0.7:
            pts += 4
        elif avg_r >= 0.5:
            pts += 2

    return min(pts, 20.0)


def _score_cash_quality_loan_book(parsed: Dict, raw_out: Dict) -> float:
    """Cash-quality variant for banks / HFCs / NBFCs. See `_score_cash_quality`
    docstring for rationale."""
    pts = 0.0
    raw_out["cash_quality_variant"] = "loan_book"

    npft5 = _values_recent_first(parsed.get("net_profit_yearly"), n=5)
    raw_out["net_profit_5y"] = npft5

    # Component 1: positive net-profit years (0..10)
    pos_npft = sum(1 for v in npft5 if v > 0) if npft5 else 0
    raw_out["positive_net_profit_years_in_last_5"] = pos_npft
    if pos_npft >= 5:
        pts += 10
    elif pos_npft == 4:
        pts += 7
    elif pos_npft == 3:
        pts += 4
    elif pos_npft == 2:
        pts += 1

    # Component 2: YoY net-profit growth years (0..6)
    # npft5 is most-recent-first; YoY growth = npft5[i] > npft5[i+1]
    growth_years = 0
    if npft5 and len(npft5) >= 2:
        for i in range(min(4, len(npft5) - 1)):
            a, b = npft5[i], npft5[i + 1]
            if a is not None and b is not None and b > 0 and a > b:
                growth_years += 1
    raw_out["net_profit_yoy_growth_years_in_last_5"] = growth_years
    if growth_years >= 4:
        pts += 6
    elif growth_years == 3:
        pts += 4
    elif growth_years == 2:
        pts += 2

    # Component 3: net-profit smoothness (coefficient of variation; 0..4)
    if npft5 and len(npft5) >= 3:
        positives = [v for v in npft5 if v is not None and v > 0]
        if len(positives) >= 3:
            mean = sum(positives) / len(positives)
            var = sum((x - mean) ** 2 for x in positives) / len(positives)
            sd = math.sqrt(var)
            cv = (sd / mean) if mean > 0 else None
            raw_out["net_profit_5y_cv"] = cv
            if cv is not None:
                if cv <= 0.15:
                    pts += 4
                elif cv <= 0.30:
                    pts += 3
                elif cv <= 0.50:
                    pts += 1

    return min(pts, 20.0)


# ---------- Bucket 3: Solvency (max 15) ----------


def _score_solvency(parsed: Dict, raw_out: Dict, is_bank: bool) -> float:
    """
    Non-bank: D/E (0..8) + interest coverage (0..7).
    Bank:     D/E meaningless. Use ROE consistency proxy (0..15) instead so
              the cap stays the same.
    """
    if is_bank:
        # Bank proxy: years with ROE >= 12% in last 5 (sustainable spread)
        roe5 = _values_recent_first(parsed.get("roe_yearly"), n=5)
        good_years = sum(1 for v in roe5 if v >= 12) if roe5 else 0
        raw_out["bank_roe_geq12_years_in_last_5"] = good_years
        raw_out["bank_solvency_proxy"] = True
        if good_years >= 5:
            return 15.0
        if good_years == 4:
            return 12.0
        if good_years == 3:
            return 8.0
        if good_years == 2:
            return 4.0
        return 1.0

    pts = 0.0

    de = parsed.get("debt_equity")
    raw_out["debt_equity"] = de
    if de is None:
        pts += 4  # neutral
    elif de <= 0.3:
        pts += 8
    elif de <= 0.7:
        pts += 6
    elif de <= 1.0:
        pts += 4
    elif de <= 2.0:
        pts += 2

    # Interest coverage: latest operating profit / interest. We use most-
    # recent year only (multi-year is already covered by debt/equity trend).
    op = _values_recent_first(parsed.get("operating_profit_yearly"), n=1)
    interest = _values_recent_first(parsed.get("interest_yearly"), n=1)
    icov = None
    if op and interest and interest[0] not in (0, None):
        icov = op[0] / interest[0]
    raw_out["interest_coverage_latest"] = icov
    if icov is None:
        pts += 3  # neutral
    elif icov >= 8:
        pts += 7
    elif icov >= 5:
        pts += 6
    elif icov >= 3:
        pts += 4
    elif icov >= 1.5:
        pts += 2

    return min(pts, 15.0)


# ---------- Bucket 4: Growth (max 20) ----------


def _score_growth(parsed: Dict, raw_out: Dict) -> float:
    """
    Components (out of 20):
      - Revenue 5y CAGR    (0..8)
      - EPS 5y CAGR        (0..8)
      - No-negative-yoy revenue years in last 5 (0..4)
    """
    pts = 0.0

    rev = _values_recent_first(parsed.get("revenue_yearly"), n=6)  # need 6 for 5y CAGR
    raw_out["revenue_5y_history"] = rev
    rev_cagr = _cagr(rev, years=5)
    raw_out["revenue_5y_cagr_pct"] = rev_cagr
    if rev_cagr is not None:
        if rev_cagr >= 20:
            pts += 8
        elif rev_cagr >= 12:
            pts += 6
        elif rev_cagr >= 8:
            pts += 4
        elif rev_cagr >= 4:
            pts += 2

    eps = _values_recent_first(parsed.get("eps_yearly"), n=6)
    raw_out["eps_5y_history"] = eps
    eps_cagr = _cagr(eps, years=5)
    raw_out["eps_5y_cagr_pct"] = eps_cagr
    if eps_cagr is not None:
        if eps_cagr >= 20:
            pts += 8
        elif eps_cagr >= 12:
            pts += 6
        elif eps_cagr >= 8:
            pts += 4
        elif eps_cagr >= 4:
            pts += 2

    # No-negative-YoY revenue years in last 5
    if len(rev) >= 5:
        # rev is most-recent-first; consecutive YoY = rev[i] vs rev[i+1]
        neg_years = sum(1 for i in range(min(4, len(rev) - 1))
                        if rev[i] < rev[i + 1])
        raw_out["revenue_yoy_decline_years_in_last_5"] = neg_years
        if neg_years == 0:
            pts += 4
        elif neg_years == 1:
            pts += 2

    return min(pts, 20.0)


# ---------- Bucket 5: Governance (max 20) ----------


def _score_governance(parsed: Dict, raw_out: Dict) -> float:
    """
    Components (out of 20):
      - Promoter holding latest          (0..8)
      - Promoter pledge latest (lower=better)   (0..6)
      - Holding stability (low std-dev of promoter % over last 8 quarters)
                                                (0..6)
    Auditor / SEBI orders are NOT scraped in Phase A (no clean section on
    screener); future enhancement can add them. We don't penalise their
    absence — those points come from the other governance signals instead.
    """
    pts = 0.0
    sh = parsed.get("shareholding_quarterly") or []
    latest = sh[0] if sh else {}

    prom = latest.get("promoter_pct")
    raw_out["promoter_holding_pct"] = prom
    if prom is None:
        pts += 4  # neutral
    elif prom >= 50:
        pts += 8
    elif prom >= 35:
        pts += 6
    elif prom >= 20:
        pts += 3
    else:
        pts += 1

    pledge = latest.get("pledged_pct")
    raw_out["promoter_pledge_pct"] = pledge
    if pledge is None:
        pts += 3  # neutral; not zero — absence of data isn't proof of clean
    elif pledge == 0.0:
        pts += 6
    elif pledge < 5:
        pts += 5
    elif pledge < 15:
        pts += 3
    elif pledge < 30:
        pts += 1
    # else 0

    # Holding stability over 8 quarters
    prom_series = [r.get("promoter_pct") for r in sh[:8]
                   if r.get("promoter_pct") is not None]
    raw_out["promoter_pct_8q"] = prom_series
    if len(prom_series) >= 4:
        mean = sum(prom_series) / len(prom_series)
        var = sum((x - mean) ** 2 for x in prom_series) / len(prom_series)
        sd = math.sqrt(var)
        raw_out["promoter_pct_8q_stddev"] = sd
        if sd <= 1.0:
            pts += 6
        elif sd <= 3.0:
            pts += 4
        elif sd <= 6.0:
            pts += 2

    return min(pts, 20.0)


# ---------- Top-level API ----------


def score_company(parsed: Dict, industry: Optional[str] = None) -> Dict[str, Any]:
    """Score a single parsed scraper dict. Pure function; no DB writes."""
    is_loan_book = _is_loan_book_business(industry)
    raw: Dict[str, Any] = {
        "is_loan_book": is_loan_book,
        "is_bank": is_loan_book,  # legacy alias for older raw-input dumps
        "industry": industry,
    }

    p_score = _score_profitability(parsed, raw)
    c_score = _score_cash_quality(parsed, raw, is_loan_book=is_loan_book)
    s_score = _score_solvency(parsed, raw, is_loan_book)
    g_score = _score_growth(parsed, raw)
    gov_score = _score_governance(parsed, raw)
    total = p_score + c_score + s_score + g_score + gov_score

    return {
        "ticker": parsed.get("ticker"),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "profitability_score": round(p_score, 2),
        "cash_quality_score": round(c_score, 2),
        "solvency_score": round(s_score, 2),
        "growth_score": round(g_score, 2),
        "governance_score": round(gov_score, 2),
        "total_score": round(total, 2),
        "raw_inputs": raw,
    }


_UPSERT_QUALITY_SQL = """
INSERT INTO lt_quality (
    ticker, scored_at,
    profitability_score, cash_quality_score, solvency_score,
    growth_score, governance_score, total_score, raw_inputs
) VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT (ticker) DO UPDATE SET
    scored_at            = EXCLUDED.scored_at,
    profitability_score  = EXCLUDED.profitability_score,
    cash_quality_score   = EXCLUDED.cash_quality_score,
    solvency_score       = EXCLUDED.solvency_score,
    growth_score         = EXCLUDED.growth_score,
    governance_score     = EXCLUDED.governance_score,
    total_score          = EXCLUDED.total_score,
    raw_inputs           = EXCLUDED.raw_inputs
"""


def score_and_store(ticker: str, industry: Optional[str] = None,
                    force: bool = False) -> Optional[Dict[str, Any]]:
    """Scrape (or read cache) -> score -> upsert into lt_quality. Returns the
    score dict, or None if scraping failed."""
    parsed = fetch_company(ticker, force=force)
    if not parsed:
        return None
    sc = score_company(parsed, industry=industry)
    with get_conn() as conn:
        conn.execute(
            _UPSERT_QUALITY_SQL,
            (
                sc["ticker"], sc["scored_at"],
                sc["profitability_score"], sc["cash_quality_score"],
                sc["solvency_score"], sc["growth_score"],
                sc["governance_score"], sc["total_score"],
                json.dumps(sc["raw_inputs"], default=str),
            ),
        )
    return sc


def get_quality_rows(min_score: float = 0.0, limit: Optional[int] = None) -> list:
    """Read scored rows back, joined with the universe table, top-down by
    total score. Used by the dashboard's Long-Term Research tab."""
    sql = """
        SELECT q.ticker, q.scored_at, q.total_score,
               q.profitability_score, q.cash_quality_score,
               q.solvency_score, q.growth_score, q.governance_score,
               u.market_cap, u.fii_pct, u.dii_pct,
               u.fii_qoq_change, u.dii_qoq_change,
               u.promoter_holding_pct, u.promoter_pledge_pct,
               u.in_universe, u.filter_reason
        FROM lt_quality q
        LEFT JOIN lt_universe u USING (ticker)
        WHERE q.total_score >= ?
        ORDER BY q.total_score DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_conn() as conn:
        rows = conn.execute(sql, (min_score,)).fetchall()
    return [dict(r) for r in rows]


def score_universe(force: bool = False, progress_cb=None) -> Dict[str, int]:
    """Score every ticker that passed the universe filter. Should be run after
    ``longterm.universe.build_universe``.

    The industry tag stored in ``lt_universe`` (populated by the universe
    builder via yfinance) is passed through to the scorer so banks / HFCs /
    NBFCs get the loan-book Cash-Quality variant.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, industry FROM lt_universe WHERE in_universe = 1"
        ).fetchall()
    items = [(dict(r)["ticker"], dict(r).get("industry")) for r in rows]

    counts = {"total": len(items), "scored": 0, "errors": 0}
    for idx, (t, industry) in enumerate(items, 1):
        try:
            sc = score_and_store(t, industry=industry, force=force)
        except Exception as e:
            log.warning("score exception %s: %s", t, e)
            sc = None
        if sc:
            counts["scored"] += 1
        else:
            counts["errors"] += 1
        if progress_cb:
            try:
                progress_cb(idx, len(items), t, sc)
            except Exception:
                pass
        if idx % 25 == 0:
            log.info("score progress: %d/%d (errors=%d)", idx, len(items),
                     counts["errors"])
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    print(score_and_store(t))

"""
Research-grade derived metrics — the skill's "Step 2" checklist, computed.

Where the 5-bucket scorer (``longterm.quality``) reduces a company to five
0-100 numbers for ranking, this module assembles the *full set of investor-
facing fundamentals* the Stock-Analyzer skill asks for, each tagged with a
plain-English verdict word and a source. It does not throw away detail:
multi-year CAGRs, margin trends, the debt/equity trajectory, the 8-quarter
ownership history and the quarterly-EPS YoY series all survive into the output.

Inputs
------
- ``parsed``  : the dict from ``screener_scraper.fetch_company`` (Screener.in)
- ``yf_row``  : the row from ``data.fundamentals`` (yfinance) — supplies the
                live price, 52-week range, P/B, EV/EBITDA, current ratio and a
                clean latest free-cash-flow figure that Screener doesn't expose
- ``industry``: routes banks / NBFCs / HFCs away from debt & cash-flow verdicts
                that don't apply to a loan-book business

Design rules (mirrors the skill)
--------------------------------
1. Never fabricate. A metric we can't source stays ``None`` and is listed under
   ``unavailable`` so the dashboard can render "🚩 verify at source" instead of
   a made-up number.
2. Cite the source of every figure (``sources`` map: "Screener" / "yfinance").
3. Verdict words use the skill's exact thresholds (see ``_verdict_*``).
4. The output is a pure dict (JSON-serialisable) — persistence is a thin
   ``compute_and_store`` wrapper around ``lt_metrics``.

This is deliberately rule-based and recommendation-bearing: unlike the skill
(which refuses a call), the host app wants an actionable read, so we also emit
an ``overall_view`` (Strong / Moderate / Weak) and a list of ``flags``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db.models import get_conn
from longterm.quality import (
    _avg,
    _cagr,
    _is_loan_book_business,
    _values_recent_first,
)

log = logging.getLogger(__name__)


# ---------- small helpers ----------


def _round(v: Optional[float], n: int = 2) -> Optional[float]:
    return round(float(v), n) if v is not None else None


def _pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    """Simple percentage change new-vs-old, guarding zero/negative bases."""
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def _records_recent_first(parsed: Dict, key: str) -> List[Dict]:
    return parsed.get(key) or []


# ---------- verdict words (skill thresholds) ----------


def _verdict_de(de: Optional[float]) -> Optional[str]:
    if de is None:
        return None
    if de < 1:
        return "Safe"
    if de <= 2:
        return "Moderate"
    return "Leveraged"


def _verdict_interest_cover(ic: Optional[float]) -> Optional[str]:
    if ic is None:
        return None
    if ic > 3:
        return "Healthy"
    if ic >= 1.5:
        return "Watch"
    return "Risk"


def _verdict_current_ratio(cr: Optional[float]) -> Optional[str]:
    if cr is None:
        return None
    if cr > 1.5:
        return "Comfortable"
    if cr >= 1.0:
        return "Watch"
    return "Risk"


def _verdict_return(v: Optional[float]) -> Optional[str]:
    """ROE / ROCE band: >15 Good, 10-15 Average, <10 Weak."""
    if v is None:
        return None
    if v > 15:
        return "Good"
    if v >= 10:
        return "Average"
    return "Weak"


def _verdict_valuation_vs_sector(pe: Optional[float],
                                 industry_pe: Optional[float]) -> Optional[str]:
    """Cheap / Fair / Expensive vs the sector P/E (within ~10% = Fair)."""
    if pe is None or industry_pe is None or industry_pe <= 0 or pe <= 0:
        return None
    ratio = pe / industry_pe
    if ratio < 0.9:
        return "Cheap"
    if ratio <= 1.1:
        return "Fair"
    return "Expensive"


def _verdict_growth(cagr_3y: Optional[float],
                    cagr_5y: Optional[float]) -> Optional[str]:
    """Accelerating / Steady / Slowing / Declining from the 3y-vs-5y CAGR gap.

    Reads the recent (3y) trajectory against the longer (5y) base: a 3y CAGR
    meaningfully above the 5y average = the business is speeding up.
    """
    if cagr_3y is None and cagr_5y is None:
        return None
    recent = cagr_3y if cagr_3y is not None else cagr_5y
    base = cagr_5y if cagr_5y is not None else cagr_3y
    if recent is not None and recent < 0:
        return "Declining"
    if recent is None or base is None:
        return "Steady"
    if recent >= base + 2:
        return "Accelerating"
    if recent <= base - 2:
        return "Slowing"
    return "Steady"


def _verdict_fcf(latest_fcf: Optional[float],
                 cfo_series: List[float]) -> Optional[str]:
    """Strong (positive & growing) / Stable (positive & flat) / Concern (neg)."""
    # Prefer the clean yfinance FCF for sign; fall back to latest CFO.
    sign_val = latest_fcf if latest_fcf is not None else (
        cfo_series[0] if cfo_series else None)
    if sign_val is None:
        return None
    if sign_val < 0:
        return "Concern"
    # Growing vs flat: compare latest CFO to the average of the prior years.
    if len(cfo_series) >= 3:
        prior_avg = _avg(cfo_series[1:])
        if prior_avg is not None and prior_avg > 0:
            if cfo_series[0] >= prior_avg * 1.1:
                return "Strong"
    return "Stable"


# ---------- component builders ----------


def _build_price(parsed: Dict, yf: Dict) -> Dict[str, Any]:
    cmp_ = yf.get("current_price")
    hi = yf.get("fifty_two_week_high")
    lo = yf.get("fifty_two_week_low")
    return {
        "cmp": _round(cmp_),
        "fifty_two_week_high": _round(hi),
        "fifty_two_week_low": _round(lo),
        "pct_below_52w_high": _round(_pct_change(cmp_, hi)) if (cmp_ and hi) else None,
        "pct_above_52w_low": _round(_pct_change(cmp_, lo)) if (cmp_ and lo) else None,
        "face_value": _round(parsed.get("face_value")),
        "book_value": _round(yf.get("book_value")),
    }


def _build_valuation(parsed: Dict, yf: Dict) -> Dict[str, Any]:
    pe = yf.get("pe_ratio") if yf.get("pe_ratio") is not None else parsed.get("pe")
    industry_pe = parsed.get("industry_pe")
    return {
        "pe": _round(pe),
        "industry_pe": _round(industry_pe),
        "pb": _round(yf.get("price_to_book")),
        "ev_ebitda": _round(yf.get("ev_to_ebitda")),
        "pe_vs_sector": _verdict_valuation_vs_sector(pe, industry_pe),
        # Screener/yfinance don't expose the stock's OWN 5-yr average multiple
        # in a parseable form. Per the skill we flag rather than fabricate.
        "own_5y_average_note": (
            "Own 5-yr average P/E not available from source — "
            "verify the 'Median PE' on screener.in"
        ),
    }


def _build_growth(parsed: Dict) -> Dict[str, Any]:
    rev = _values_recent_first(parsed.get("revenue_yearly"), n=6)
    npft = _values_recent_first(parsed.get("net_profit_yearly"), n=6)
    eps = _values_recent_first(parsed.get("eps_yearly"), n=6)

    rev3, rev5 = _cagr(rev, years=3), _cagr(rev, years=5)
    np3, np5 = _cagr(npft, years=3), _cagr(npft, years=5)
    eps3, eps5 = _cagr(eps, years=3), _cagr(eps, years=5)

    return {
        "revenue_cagr_3y": _round(rev3),
        "revenue_cagr_5y": _round(rev5),
        "net_profit_cagr_3y": _round(np3),
        "net_profit_cagr_5y": _round(np5),
        "eps_cagr_3y": _round(eps3),
        "eps_cagr_5y": _round(eps5),
        # Headline trend reads off the most complete pair available.
        "trend": _verdict_growth(
            rev3 if rev3 is not None else eps3,
            rev5 if rev5 is not None else eps5,
        ),
    }


def _build_margins(parsed: Dict) -> Dict[str, Any]:
    opm = _values_recent_first(parsed.get("opm_yearly"), n=5)  # EBITDA margin proxy
    rev = _values_recent_first(parsed.get("revenue_yearly"), n=5)
    npft = _values_recent_first(parsed.get("net_profit_yearly"), n=5)
    net_margin_trend: List[Optional[float]] = []
    for r, n in zip(rev, npft):
        net_margin_trend.append(_round((n / r) * 100.0) if r and r > 0 else None)
    return {
        "ebitda_margin_latest": _round(opm[0]) if opm else None,
        "ebitda_margin_5y_trend": [_round(v) for v in opm],
        "net_margin_latest": net_margin_trend[0] if net_margin_trend else None,
        "net_margin_5y_trend": net_margin_trend,
    }


def _build_profitability(parsed: Dict, yf: Dict) -> Dict[str, Any]:
    roe_series = _values_recent_first(parsed.get("roe_yearly"), n=5)
    roce_series = _values_recent_first(parsed.get("roce_yearly"), n=5)
    roe_cur = parsed.get("roe_pct")
    roce_cur = parsed.get("roce_pct")
    roe5 = _avg(roe_series)
    roce5 = _avg(roce_series)
    roe3 = _avg(roe_series[:3])
    roce3 = _avg(roce_series[:3])
    return {
        "roe_current": _round(roe_cur),
        "roe_3y_avg": _round(roe3),
        "roe_5y_avg": _round(roe5),
        "roe_verdict": _verdict_return(roe5 if roe5 is not None else roe_cur),
        "roce_current": _round(roce_cur),
        "roce_3y_avg": _round(roce3),
        "roce_5y_avg": _round(roce5),
        "roce_verdict": _verdict_return(roce5 if roce5 is not None else roce_cur),
    }


def _build_health(parsed: Dict, yf: Dict, is_loan_book: bool) -> Dict[str, Any]:
    # --- Debt/equity trend, reconstructed from the balance sheet ---
    borrow = _values_recent_first(parsed.get("borrowings_yearly"), n=6)
    equity = _values_recent_first(parsed.get("equity_capital_yearly"), n=6)
    reserves = _values_recent_first(parsed.get("reserves_yearly"), n=6)
    de_trend: List[Optional[float]] = []
    for i in range(min(len(borrow), len(equity), len(reserves))):
        net_worth = (equity[i] or 0) + (reserves[i] or 0)
        de_trend.append(_round(borrow[i] / net_worth) if net_worth > 0 else None)
    de_latest = parsed.get("debt_equity")
    if de_latest is None and de_trend:
        de_latest = de_trend[0]

    # --- Interest-coverage series (operating profit / interest) ---
    op = _values_recent_first(parsed.get("operating_profit_yearly"), n=5)
    interest = _values_recent_first(parsed.get("interest_yearly"), n=5)
    ic_trend: List[Optional[float]] = []
    for i in range(min(len(op), len(interest))):
        ic_trend.append(_round(op[i] / interest[i]) if interest[i] else None)
    ic_latest = next((v for v in ic_trend if v is not None), None)

    # --- Cash flow ---
    cfo_series = _values_recent_first(parsed.get("cfo_yearly"), n=5)
    fcf_latest = yf.get("free_cashflow")

    out = {
        "debt_to_equity": _round(de_latest),
        "de_5y_trend": de_trend,
        "interest_coverage_latest": ic_latest,
        "interest_coverage_5y_trend": ic_trend,
        "current_ratio": _round(yf.get("current_ratio")),
        "free_cashflow_latest": _round(fcf_latest),
        "operating_cashflow_5y_trend": [_round(v) for v in cfo_series],
    }
    # Verdicts. Banks/NBFCs run a deposit-funded model, so D/E, interest cover
    # and a current ratio are not meaningful — suppress those words for them.
    if is_loan_book:
        out["de_verdict"] = "n/a (lender)"
        out["interest_coverage_verdict"] = "n/a (lender)"
        out["current_ratio_verdict"] = "n/a (lender)"
        out["fcf_verdict"] = "n/a (lender)"
    else:
        out["de_verdict"] = _verdict_de(de_latest)
        out["interest_coverage_verdict"] = _verdict_interest_cover(ic_latest)
        out["current_ratio_verdict"] = _verdict_current_ratio(yf.get("current_ratio"))
        out["fcf_verdict"] = _verdict_fcf(fcf_latest, cfo_series)
    return out


def _build_ownership(parsed: Dict) -> Dict[str, Any]:
    sh = parsed.get("shareholding_quarterly") or []
    latest = sh[0] if sh else {}

    def series(key: str, n: int = 8) -> List[Optional[float]]:
        return [r.get(key) for r in sh[:n]]

    def qoq(key: str) -> Optional[float]:
        if len(sh) < 2 or sh[0].get(key) is None or sh[1].get(key) is None:
            return None
        return _round(sh[0][key] - sh[1][key])

    pledge = latest.get("pledged_pct")
    return {
        "promoter_latest": _round(latest.get("promoter_pct")),
        "promoter_8q": series("promoter_pct"),
        "promoter_qoq": qoq("promoter_pct"),
        "pledge_latest": _round(pledge),
        "pledge_over_10pct": (pledge is not None and pledge > 10.0),
        "fii_latest": _round(latest.get("fii_pct")),
        "fii_8q": series("fii_pct"),
        "fii_qoq": qoq("fii_pct"),
        "dii_latest": _round(latest.get("dii_pct")),
        "dii_8q": series("dii_pct"),
        "dii_qoq": qoq("dii_pct"),
    }


def _build_dividend(parsed: Dict, yf: Dict) -> Dict[str, Any]:
    payout = _values_recent_first(parsed.get("dividend_payout_yearly"), n=1)
    # yfinance dividendYield is a fraction (0.012); screener stores % (1.2).
    y = yf.get("dividend_yield")
    yield_pct = _round(y * 100.0) if (y is not None and y < 1) else _round(y)
    if yield_pct is None:
        yield_pct = _round(parsed.get("dividend_yield_pct"))
    return {
        "yield_pct": yield_pct,
        "payout_pct": _round(payout[0]) if payout else None,
    }


def _build_quarterly_eps(parsed: Dict) -> List[Dict[str, Any]]:
    """Last 8 quarters of EPS with YoY (quarter i vs quarter i+4)."""
    recs = parsed.get("eps_quarterly") or []
    vals = [r.get("value") for r in recs]
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(recs[:8]):
        yoy = None
        if i + 4 < len(vals) and vals[i] is not None and vals[i + 4] not in (None, 0):
            yoy = _round(_pct_change(vals[i], vals[i + 4]))
        out.append({"period": r.get("period"), "eps": _round(r.get("value")),
                    "yoy_pct": yoy})
    return out


# ---------- flags + confidence + overall view ----------


def _collect_flags(m: Dict[str, Any], is_loan_book: bool) -> List[str]:
    flags: List[str] = []
    own = m["ownership"]
    health = m["health"]
    prof = m["profitability"]
    val = m["valuation"]
    growth = m["growth"]

    if own["pledge_over_10pct"]:
        flags.append(f"Promoter pledge {own['pledge_latest']}% (> 10% — governance risk)")
    if own.get("promoter_qoq") is not None and own["promoter_qoq"] <= -2:
        flags.append(f"Promoter holding fell {abs(own['promoter_qoq'])}pp QoQ")

    if not is_loan_book:
        if health.get("de_verdict") == "Leveraged":
            flags.append(f"High leverage — D/E {health['debt_to_equity']} (> 2)")
        if health.get("interest_coverage_verdict") == "Risk":
            flags.append(f"Thin interest cover ({health['interest_coverage_latest']}x < 1.5)")
        if health.get("current_ratio_verdict") == "Risk":
            flags.append(f"Current ratio {health['current_ratio']} (< 1 — liquidity)")
        if health.get("fcf_verdict") == "Concern":
            flags.append("Negative free cash flow")

    if prof.get("roe_5y_avg") is not None and prof["roe_5y_avg"] < 10:
        flags.append(f"Weak 5-yr ROE ({prof['roe_5y_avg']}% < 10%)")
    if growth.get("trend") == "Declining":
        flags.append("Declining revenue/earnings trend")
    if val.get("pe_vs_sector") == "Expensive" and (val.get("pe") or 0) > 40:
        flags.append(f"Rich valuation — P/E {val['pe']} vs sector {val['industry_pe']}")

    qeps = m.get("quarterly_eps_yoy") or []
    if qeps and qeps[0].get("yoy_pct") is not None and qeps[0]["yoy_pct"] < 0:
        flags.append(f"Latest quarter EPS down {abs(qeps[0]['yoy_pct'])}% YoY")
    return flags


# Keys that must be present for a "complete" data pack (for the confidence grade).
_CONFIDENCE_KEYS = [
    ("price", "cmp"), ("price", "fifty_two_week_high"),
    ("valuation", "pe"), ("valuation", "pb"), ("valuation", "ev_ebitda"),
    ("growth", "revenue_cagr_5y"), ("growth", "eps_cagr_5y"),
    ("margins", "ebitda_margin_latest"), ("margins", "net_margin_latest"),
    ("profitability", "roe_5y_avg"), ("profitability", "roce_5y_avg"),
    ("health", "debt_to_equity"), ("health", "current_ratio"),
    ("health", "free_cashflow_latest"),
    ("ownership", "promoter_latest"), ("ownership", "fii_latest"),
    ("dividend", "yield_pct"),
]


def _data_confidence(m: Dict[str, Any]) -> tuple[str, List[str]]:
    present = 0
    unavailable: List[str] = []
    for sect, key in _CONFIDENCE_KEYS:
        if m.get(sect, {}).get(key) is not None:
            present += 1
        else:
            unavailable.append(f"{sect}.{key}")
    ratio = present / len(_CONFIDENCE_KEYS)
    grade = "High" if ratio >= 0.8 else "Moderate" if ratio >= 0.5 else "Low"
    return grade, unavailable


def _overall_view(quality_score: Optional[float], flags: List[str]) -> str:
    """Strong / Moderate / Weak. Anchored on the 5-bucket quality score when
    available, then nudged down by the number of red flags."""
    if quality_score is None:
        # No quality score: infer purely from flags.
        if len(flags) >= 3:
            return "Weak"
        if len(flags) >= 1:
            return "Moderate"
        return "Moderate"
    base = "Strong" if quality_score >= 70 else "Moderate" if quality_score >= 50 else "Weak"
    if base == "Strong" and len(flags) >= 2:
        return "Moderate"
    if base == "Moderate" and len(flags) >= 3:
        return "Weak"
    return base


# ---------- public API ----------


def compute_metrics(parsed: Dict, yf_row: Optional[Dict] = None,
                    industry: Optional[str] = None,
                    quality_score: Optional[float] = None) -> Dict[str, Any]:
    """Build the full research-metrics pack for one company. Pure function."""
    yf = yf_row or {}
    # Prefer the explicit industry arg, then the yfinance row's industry tag.
    industry = industry or yf.get("industry")
    is_loan_book = _is_loan_book_business(industry)

    m: Dict[str, Any] = {
        "ticker": (parsed.get("ticker") or yf.get("ticker") or "").upper(),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "industry": industry,
        "is_loan_book": is_loan_book,
        "price": _build_price(parsed, yf),
        "valuation": _build_valuation(parsed, yf),
        "growth": _build_growth(parsed),
        "margins": _build_margins(parsed),
        "profitability": _build_profitability(parsed, yf),
        "health": _build_health(parsed, yf, is_loan_book),
        "ownership": _build_ownership(parsed),
        "dividend": _build_dividend(parsed, yf),
        "quarterly_eps_yoy": _build_quarterly_eps(parsed),
        "sources": {
            "price": "yfinance", "valuation_pe": "yfinance/Screener",
            "valuation_pb_ev": "yfinance", "industry_pe": "Screener",
            "growth": "Screener", "margins": "Screener",
            "profitability": "Screener", "debt_equity_trend": "Screener",
            "interest_coverage": "Screener", "current_ratio": "yfinance",
            "free_cashflow": "yfinance", "operating_cashflow": "Screener",
            "ownership": "Screener", "dividend_payout": "Screener",
            "quarterly_eps": "Screener",
        },
    }
    m["flags"] = _collect_flags(m, is_loan_book)
    grade, unavailable = _data_confidence(m)
    m["data_confidence"] = grade
    m["unavailable"] = unavailable
    m["overall_view"] = _overall_view(quality_score, m["flags"])
    m["quality_score"] = quality_score
    return m


_UPSERT_METRICS_SQL = """
INSERT INTO lt_metrics (
    ticker, computed_at, data_confidence, overall_view, flag_count, metrics, flags
) VALUES (?,?,?,?,?,?,?)
ON CONFLICT (ticker) DO UPDATE SET
    computed_at     = EXCLUDED.computed_at,
    data_confidence = EXCLUDED.data_confidence,
    overall_view    = EXCLUDED.overall_view,
    flag_count      = EXCLUDED.flag_count,
    metrics         = EXCLUDED.metrics,
    flags           = EXCLUDED.flags
"""


def store_metrics(m: Dict[str, Any]) -> None:
    """Upsert a computed metrics pack into ``lt_metrics``."""
    with get_conn() as conn:
        conn.execute(
            _UPSERT_METRICS_SQL,
            (
                m["ticker"], m["computed_at"], m.get("data_confidence"),
                m.get("overall_view"), len(m.get("flags") or []),
                json.dumps(m, default=str), json.dumps(m.get("flags") or [],
                                                       default=str),
            ),
        )


def compute_and_store(ticker: str, parsed: Optional[Dict] = None,
                      yf_row: Optional[Dict] = None,
                      industry: Optional[str] = None,
                      quality_score: Optional[float] = None,
                      force: bool = False) -> Optional[Dict[str, Any]]:
    """Compute + persist the research-metrics pack for one ticker.

    ``parsed`` / ``yf_row`` are reused when the caller already has them (the
    quality scorer passes its scrape straight through, so no double fetch). When
    omitted they're fetched (Screener HTML is 24h-cached; yfinance is 24h-cached
    in the ``fundamentals`` table), so this is cheap to call standalone too.
    """
    if parsed is None:
        from longterm.screener_scraper import fetch_company
        parsed = fetch_company(ticker, force=force)
    if not parsed:
        return None

    if yf_row is None:
        try:
            from data.fundamentals import fetch_and_store, get_cached
            yf_row = get_cached(ticker) or fetch_and_store(ticker)
        except Exception as e:
            log.debug("yfinance row unavailable for %s: %s", ticker, e)
            yf_row = {}

    m = compute_metrics(parsed, yf_row=yf_row, industry=industry,
                        quality_score=quality_score)
    try:
        store_metrics(m)
    except Exception as e:
        log.warning("store_metrics failed for %s: %s", ticker, e)
    return m


def get_metrics(ticker: str) -> Optional[Dict[str, Any]]:
    """Read back a stored metrics pack (the full JSON), or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT metrics FROM lt_metrics WHERE ticker=?", (ticker.upper(),)
        ).fetchone()
    if not row or not row["metrics"]:
        return None
    raw = row["metrics"]
    if isinstance(raw, (dict, list)):
        return raw  # postgres JSONB already decoded
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    res = compute_and_store(t)
    if res:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(f"No data for {t}")

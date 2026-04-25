"""
Fundamental data fetcher + scorer.

Primary source: yfinance — free, but has known issues for Indian stocks:
  * `earningsGrowth` / `revenueGrowth` are *single-quarter YoY snapshots*
    that swing wildly when the prior quarter had a low base. For example,
    Bank of Maharashtra (MAHABANK) shows 172.9% earnings growth on yfinance
    because the prior-year quarter was depressed; screener.in shows the
    smoothed multi-year CAGR (~27-65%) which is a more reliable read.
  * yfinance's debt/equity is not meaningful for banks (a bank's
    "borrowings" are deposits — that IS its business model).
  * yfinance's profit_margin for banks is closer to a Net Interest Margin
    derivative than a clean net margin.

What this module does about it:
  1. We DO NOT trust `info.earningsGrowth` / `info.revenueGrowth`. Instead
     we compute TTM-vs-prior-TTM growth from quarterly statements, plus a
     3-year CAGR from annual statements, and prefer the smoothed value.
  2. We tag banks (industry contains 'bank' or starts with 'credit
     services') and:
       - Set debt_to_equity to None (suppressed in dashboard with a note).
       - Pass profit_margin through but the dashboard labels it
         "Net Margin (yfinance — bank-adjusted)" with a warning.
  3. We expose `screener_url(ticker)` so the dashboard can deep-link to
     screener.in for cross-checking.

Results cached in SQLite for 24h to avoid repeat calls.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd
import yfinance as yf

from data.universe import to_yf_ticker
from db.models import get_conn

log = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24


# ---------- Helpers ----------


def _safe_num(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def is_bank(sector: str, industry: str) -> bool:
    """Heuristic: does this company's profile look like a bank/NBFC?

    yfinance puts most Indian banks under sector="Financial Services" with
    industry="Banks - Regional" / "Banks - Diversified". Insurers and AMCs
    are also Financial Services but should NOT be flagged here — their
    margin & D/E numbers are conventional.
    """
    i = (industry or "").lower()
    return "bank" in i or i.startswith("credit services")


def screener_url(ticker: str) -> str:
    """Cross-check link to screener.in for a given NSE symbol."""
    # Screener uses the bare NSE code in its URL, no .NS suffix.
    return f"https://www.screener.in/company/{ticker.upper()}/"


# ---------- Fetch raw + computed growth ----------


def _fetch_raw(ticker: str) -> Dict:
    """Return dict with both `.info` AND our self-computed growth metrics.
    Falls back gracefully — missing pieces just stay None."""
    out: Dict = {}
    try:
        t = yf.Ticker(to_yf_ticker(ticker))
    except Exception as e:
        log.debug("yf Ticker construct failed for %s: %s", ticker, e)
        return out

    try:
        info = t.info or {}
    except Exception as e:
        log.debug("yf info failed for %s: %s", ticker, e)
        info = {}

    out["info"] = info

    # ---- Compute growth ourselves from financial statements ----
    out["earnings_growth_computed"] = _compute_growth(t, kind="earnings")
    out["revenue_growth_computed"] = _compute_growth(t, kind="revenue")
    return out


def _compute_growth(t: "yf.Ticker", kind: str) -> Optional[float]:
    """
    Compute a smoothed YoY growth rate for `revenue` or `earnings`.
    Strategy:
      1. Quarterly TTM-vs-prior-TTM (sum of last 4 quarters / sum of 4
         quarters before that, minus 1). Smooths out single-quarter spikes.
      2. If quarterly data is missing or insufficient, fall back to annual
         3-year CAGR.
      3. If neither works, return None.

    Bias: this is conservative — it always smooths. The on-screen value will
    be lower than yfinance's volatile single-quarter `earningsGrowth`, but
    will line up much better with what screener.in shows.
    """
    label_map = {"revenue": ["Total Revenue"], "earnings": ["Net Income"]}

    # ----- 1. Quarterly TTM ratio -----
    try:
        q = t.quarterly_financials  # rows = line items, cols = period-end dates
        if isinstance(q, pd.DataFrame) and not q.empty:
            for label in label_map[kind]:
                if label in q.index:
                    series = q.loc[label].dropna()
                    if len(series) >= 8:
                        # Sort columns descending (newest first), then sum windows.
                        series = series.sort_index(ascending=False)
                        ttm_now = float(series.iloc[:4].sum())
                        ttm_prev = float(series.iloc[4:8].sum())
                        if ttm_prev != 0:
                            growth = (ttm_now - ttm_prev) / abs(ttm_prev)
                            # Clip wildly implausible blow-ups (low-base recovery).
                            return max(-1.0, min(5.0, growth))
                    break
    except Exception as e:
        log.debug("quarterly growth failed for %s: %s", kind, e)

    # ----- 2. Annual CAGR (3 years) -----
    try:
        a = t.financials
        if isinstance(a, pd.DataFrame) and not a.empty:
            for label in label_map[kind]:
                if label in a.index:
                    series = a.loc[label].dropna()
                    if len(series) >= 3:
                        series = series.sort_index(ascending=False)
                        recent = float(series.iloc[0])
                        old = float(series.iloc[min(3, len(series) - 1)])
                        years = min(3, len(series) - 1)
                        if old > 0 and years > 0:
                            cagr = (recent / old) ** (1 / years) - 1
                            return max(-1.0, min(5.0, cagr))
                    break
    except Exception as e:
        log.debug("annual CAGR failed for %s: %s", kind, e)

    return None


# ---------- Public API ----------


def fetch_and_store(ticker: str, force: bool = False) -> Dict:
    """
    Fetch fundamentals for a ticker and upsert into the fundamentals table.
    Returns the stored dict (including computed `fundamental_score`).
    """
    with get_conn() as conn:
        if not force:
            row = conn.execute(
                "SELECT * FROM fundamentals WHERE ticker=?", (ticker,)
            ).fetchone()
            if row:
                age = datetime.utcnow() - datetime.fromisoformat(row["fetched_at"])
                if age < timedelta(hours=CACHE_TTL_HOURS):
                    return dict(row)

    raw = _fetch_raw(ticker)
    info = raw.get("info") or {}
    if not info:
        return {}

    sector = info.get("sector") or ""
    industry = info.get("industry") or ""
    bank_flag = is_bank(sector, industry)

    # Prefer our self-computed growth (smoothed); fall back to yfinance's
    # snapshot only if we couldn't compute it ourselves. This is the key fix
    # for the MAHABANK 172.9% issue.
    earnings_growth = raw.get("earnings_growth_computed")
    if earnings_growth is None:
        earnings_growth = _safe_num(info.get("earningsGrowth"))

    revenue_growth = raw.get("revenue_growth_computed")
    if revenue_growth is None:
        revenue_growth = _safe_num(info.get("revenueGrowth"))

    # D/E: meaningless for banks (deposits ARE their liabilities).
    if bank_flag:
        debt_to_equity = None
    else:
        debt_to_equity = _safe_num(info.get("debtToEquity"))
        # yfinance reports D/E as a percentage scale (75 = 0.75) for some
        # tickers and as a ratio (0.75) for others. Normalise to ratio.
        if debt_to_equity is not None and debt_to_equity > 5:
            debt_to_equity = debt_to_equity / 100.0

    row = dict(
        ticker=ticker,
        fetched_at=datetime.utcnow().isoformat(),
        pe_ratio=_safe_num(info.get("trailingPE")),
        peg_ratio=_safe_num(info.get("pegRatio")),
        eps=_safe_num(info.get("trailingEps")),
        revenue_growth=revenue_growth,
        earnings_growth=earnings_growth,
        debt_to_equity=debt_to_equity,
        roe=_safe_num(info.get("returnOnEquity")),
        profit_margin=_safe_num(info.get("profitMargins")),
        market_cap=_safe_num(info.get("marketCap")),
        dividend_yield=_safe_num(info.get("dividendYield")),
        sector=sector,
        industry=industry,
    )
    row["fundamental_score"] = score_fundamentals(row, is_bank_=bank_flag)

    with get_conn() as conn:
        # Postgres-compatible UPSERT (also valid in SQLite ≥ 3.24).
        # Replaces the previous INSERT OR REPLACE, which is SQLite-only.
        conn.execute(
            """INSERT INTO fundamentals (
                ticker, fetched_at, pe_ratio, peg_ratio, eps, revenue_growth,
                earnings_growth, debt_to_equity, roe, profit_margin, market_cap,
                dividend_yield, sector, industry, fundamental_score
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (ticker) DO UPDATE SET
                fetched_at        = EXCLUDED.fetched_at,
                pe_ratio          = EXCLUDED.pe_ratio,
                peg_ratio         = EXCLUDED.peg_ratio,
                eps               = EXCLUDED.eps,
                revenue_growth    = EXCLUDED.revenue_growth,
                earnings_growth   = EXCLUDED.earnings_growth,
                debt_to_equity    = EXCLUDED.debt_to_equity,
                roe               = EXCLUDED.roe,
                profit_margin     = EXCLUDED.profit_margin,
                market_cap        = EXCLUDED.market_cap,
                dividend_yield    = EXCLUDED.dividend_yield,
                sector            = EXCLUDED.sector,
                industry          = EXCLUDED.industry,
                fundamental_score = EXCLUDED.fundamental_score""",
            (
                row["ticker"], row["fetched_at"], row["pe_ratio"], row["peg_ratio"],
                row["eps"], row["revenue_growth"], row["earnings_growth"],
                row["debt_to_equity"], row["roe"], row["profit_margin"],
                row["market_cap"], row["dividend_yield"], row["sector"],
                row["industry"], row["fundamental_score"],
            ),
        )
    return row


# ---------- Scoring ----------


def _bucket(val: Optional[float], thresholds: list[tuple[float, float]]) -> float:
    """
    Map a value to 0-100 based on thresholds: list of (cutoff, points).
    First matching cutoff (val <= cutoff) wins; if none, returns last entry's points.
    """
    if val is None:
        return 50.0  # neutral when missing
    for cutoff, pts in thresholds:
        if val <= cutoff:
            return pts
    return thresholds[-1][1]


def score_fundamentals(d: Dict, is_bank_: bool = False) -> float:
    """
    Composite fundamental score 0-100.
    Simple additive model weighted across P/E, growth, profitability, leverage.
    For banks: skip D/E entirely and rebalance weights.
    """
    # ROE: higher is better
    roe_pts = _bucket(d.get("roe"), [(0.05, 20), (0.10, 40), (0.15, 60), (0.20, 80), (float("inf"), 95)])

    # Earnings growth: positive good, negative bad
    eg_pts = _bucket(
        d.get("earnings_growth"),
        [(-0.2, 10), (0.0, 35), (0.05, 55), (0.15, 75), (float("inf"), 90)],
    )

    # Revenue growth
    rg_pts = _bucket(
        d.get("revenue_growth"),
        [(-0.1, 15), (0.0, 40), (0.05, 60), (0.15, 80), (float("inf"), 90)],
    )

    # P/E: penalise extremes (negative or super high)
    pe = d.get("pe_ratio")
    if pe is None:
        pe_pts = 50
    elif pe <= 0:
        pe_pts = 20
    elif pe < 15:
        pe_pts = 85
    elif pe < 25:
        pe_pts = 75
    elif pe < 40:
        pe_pts = 55
    elif pe < 70:
        pe_pts = 35
    else:
        pe_pts = 15

    # Profit margin: higher is better
    pm_pts = _bucket(
        d.get("profit_margin"),
        [(0.0, 10), (0.05, 40), (0.10, 60), (0.20, 80), (float("inf"), 90)],
    )

    if is_bank_:
        # No D/E weight; redistribute its 0.15 across remaining factors.
        score = (
            roe_pts * 0.30          # ROE matters more for banks
            + eg_pts * 0.20
            + rg_pts * 0.15
            + pe_pts * 0.20
            + pm_pts * 0.15
        )
    else:
        # Debt/Equity (already normalised to ratio in fetch_and_store)
        de_pts = _bucket(
            d.get("debt_to_equity"),
            [(0.3, 90), (0.7, 70), (1.0, 55), (2.0, 35), (float("inf"), 15)],
        )
        score = (
            roe_pts * 0.25
            + de_pts * 0.15
            + eg_pts * 0.15
            + rg_pts * 0.15
            + pe_pts * 0.15
            + pm_pts * 0.15
        )
    return round(float(score), 2)


def get_cached(ticker: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM fundamentals WHERE ticker=?", (ticker,)
        ).fetchone()
    return dict(row) if row else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(fetch_and_store("RELIANCE"))

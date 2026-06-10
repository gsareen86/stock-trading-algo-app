"""
Unified universe (Phase 4) — Screener pipeline as the source of truth.

Previously the positional scanner's universe (pos_universe) was populated
only by a manually uploaded Screener CSV, while the long-term module built
its own scraped universe (lt_universe + lt_quality) with different filters.
Two parallel truths eventually produce conflicting decisions.

sync_lt_to_pos_universe() makes the scraped pipeline feed the scanner:

  lt_universe (hard filters)  ─┐
  lt_quality  (5-bucket score) ┼─→  positional dual-track fundamental
  Stage-0 hygiene (ASM/GSM,    │    thresholds → upsert into pos_universe
  liquidity)                  ─┘

The CSV upload keeps working (rows are upserted by ticker, never wiped),
but becomes optional. Scheduled weekly from the positional daemon via
longterm.tasks.run_phase_a(sync_positional=True).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


def _is_financial(sector: str, industry: str, is_loan_book: bool) -> bool:
    from config import POSITIONAL_FINANCIAL_SECTORS
    if is_loan_book:
        return True
    for val in (sector, industry):
        v = (val or "").lower()
        if any(kw in v for kw in POSITIONAL_FINANCIAL_SECTORS):
            return True
    return False


def _fundamental_reasons(is_fin: bool, roce, roe, sales_growth, de) -> list[str]:
    """Positional dual-track thresholds (same bars as the CSV path)."""
    from config import (
        POSITIONAL_BANK_MIN_ROE, POSITIONAL_BANK_MIN_SALES_GROWTH,
        POSITIONAL_FUND_MAX_DE, POSITIONAL_FUND_MIN_ROCE,
        POSITIONAL_FUND_MIN_ROE, POSITIONAL_FUND_MIN_SALES_GROWTH,
    )
    reasons: list[str] = []
    if is_fin:
        if roe is not None and roe < POSITIONAL_BANK_MIN_ROE:
            reasons.append(f"ROE {roe:.1f}% < {POSITIONAL_BANK_MIN_ROE}%")
        if sales_growth is not None and sales_growth < POSITIONAL_BANK_MIN_SALES_GROWTH:
            reasons.append(f"Growth {sales_growth:.1f}% < {POSITIONAL_BANK_MIN_SALES_GROWTH}%")
        # NPA data isn't in the scraped quality inputs; the quality score's
        # bank-aware cash/solvency buckets stand in for asset quality here.
    else:
        if roce is not None and roce < POSITIONAL_FUND_MIN_ROCE:
            reasons.append(f"ROCE {roce:.1f}% < {POSITIONAL_FUND_MIN_ROCE}%")
        if roe is not None and roe < POSITIONAL_FUND_MIN_ROE:
            reasons.append(f"ROE {roe:.1f}% < {POSITIONAL_FUND_MIN_ROE}%")
        if sales_growth is not None and sales_growth < POSITIONAL_FUND_MIN_SALES_GROWTH:
            reasons.append(f"Growth {sales_growth:.1f}% < {POSITIONAL_FUND_MIN_SALES_GROWTH}%")
        if de is not None and de > POSITIONAL_FUND_MAX_DE:
            reasons.append(f"D/E {de:.2f} > {POSITIONAL_FUND_MAX_DE}")
    return reasons


def _pe_from_fundamentals(conn, ticker: str) -> Optional[float]:
    try:
        row = conn.execute(
            "SELECT pe_ratio FROM fundamentals WHERE ticker = ?", (ticker,)
        ).fetchone()
        return float(row["pe_ratio"]) if row and row["pe_ratio"] is not None else None
    except Exception:
        return None


def sync_lt_to_pos_universe(check_liquidity: bool = True,
                            min_quality: Optional[float] = None) -> dict:
    """Upsert lt_universe/lt_quality survivors into pos_universe.

    Gates, in order: lt_universe.in_universe=1 → quality ≥ min_quality
    (default POSITIONAL_MIN_QUALITY_SCORE) → positional dual-track
    fundamentals → Stage-0 hygiene (surveillance always, liquidity optional).
    Returns {scanned, passed, failed, errors}.
    """
    from config import POSITIONAL_MIN_QUALITY_SCORE
    from db.models import get_conn
    from data.hygiene import hygiene_check

    if min_quality is None:
        min_quality = POSITIONAL_MIN_QUALITY_SCORE

    try:
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute(
                """SELECT u.ticker, u.sector, u.market_cap,
                          q.total_score, q.raw_inputs
                   FROM lt_universe u
                   JOIN lt_quality q ON q.ticker = u.ticker
                   WHERE u.in_universe = 1
                   ORDER BY u.market_cap DESC"""
            ).fetchall()]
    except Exception as e:
        log.warning("[universe_sync] read failed: %s", e)
        return {"scanned": 0, "passed": 0, "failed": 0, "errors": [str(e)]}

    now_iso = datetime.now(timezone.utc).isoformat()
    passed = failed = 0
    errors: list[str] = []

    for row in rows:
        ticker = row["ticker"]
        try:
            raw = json.loads(row.get("raw_inputs") or "{}")
        except (TypeError, ValueError):
            raw = {}

        roce = raw.get("roce_5y_avg")
        roe = raw.get("roe_5y_avg")
        sales_growth = raw.get("revenue_5y_cagr_pct")
        de = raw.get("debt_equity")
        industry = raw.get("industry") or ""
        is_fin = _is_financial(row.get("sector") or "", industry,
                               bool(raw.get("is_loan_book")))

        reasons: list[str] = []
        quality = row.get("total_score")
        if quality is not None and float(quality) < float(min_quality):
            reasons.append(f"quality {float(quality):.0f} < {min_quality}")
        reasons += _fundamental_reasons(is_fin, roce, roe, sales_growth, de)

        if not reasons:  # only pay the hygiene cost for fundamental survivors
            hc = hygiene_check(ticker, check_liquidity=check_liquidity)
            reasons += hc["reasons"]

        in_universe = 0 if reasons else 1
        filter_reason = ("lt_sync: " + "; ".join(reasons)) if reasons else None

        yf_ticker = ticker if ticker.endswith((".NS", ".BO")) else ticker + ".NS"
        try:
            with get_conn() as conn:
                pe = _pe_from_fundamentals(conn, ticker)
                conn.execute(
                    """INSERT INTO pos_universe
                       (ticker, company_name, sector, market_cap, roce, roe,
                        sales_growth, debt_to_equity, pe_ratio, imported_at,
                        in_universe, filter_reason)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(ticker) DO UPDATE SET
                           sector=excluded.sector,
                           market_cap=excluded.market_cap,
                           roce=excluded.roce,
                           roe=excluded.roe,
                           sales_growth=excluded.sales_growth,
                           debt_to_equity=excluded.debt_to_equity,
                           pe_ratio=COALESCE(excluded.pe_ratio, pos_universe.pe_ratio),
                           imported_at=excluded.imported_at,
                           in_universe=excluded.in_universe,
                           filter_reason=excluded.filter_reason""",
                    (yf_ticker, "", row.get("sector") or "", row.get("market_cap"),
                     roce, roe, sales_growth,
                     de if not is_fin else None, pe, now_iso,
                     in_universe, filter_reason),
                )
            if in_universe:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            errors.append(f"{ticker}: {e}")

    log.info("[universe_sync] lt→pos sync: %d scanned, %d in universe, %d filtered",
             len(rows), passed, failed)
    return {"scanned": len(rows), "passed": passed, "failed": failed,
            "errors": errors[:10]}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(sync_lt_to_pos_universe())

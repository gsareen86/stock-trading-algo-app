"""
Fundamental Universe Manager — Screener.in CSV-based whitelist.

Workflow:
  1. User runs a query on https://screener.in/explore/ (Top 500/750 NSE stocks)
     with these filters applied on the site:
       - ROCE > 15%
       - ROE  > 15%
       - Sales Growth (3yr CAGR) > 15%
       - Debt to Equity < 1

  2. User exports the results as a CSV file from Screener.in.

  3. User uploads the CSV via the dashboard (Positional tab → Universe Manager).
     The app calls process_screener_csv() which applies the filters in code
     (double-check) and stores the whitelist in pos_universe.

  4. The EOD scanner calls get_fundamental_universe() to get the list of
     approved tickers for the daily technical scan.

Expected CSV columns (Screener.in export format):
  Name, NSE Code (or Symbol), ROCE %, ROE %, Sales Growth %, Debt / Equity,
  Market Capitalization, P/E, Sector (optional)

Column names are matched case-insensitively and flexibly.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from config import (
    POSITIONAL_FUND_MAX_DE,
    POSITIONAL_FUND_MIN_ROCE,
    POSITIONAL_FUND_MIN_ROE,
    POSITIONAL_FUND_MIN_SALES_GROWTH,
)

log = logging.getLogger(__name__)

# Column name variants from Screener.in exports
_COL_MAP = {
    "ticker":       ["nse code", "symbol", "nse symbol", "ticker", "code"],
    "company_name": ["name", "company", "company name"],
    "roce":         ["roce %", "roce", "return on capital employed %",
                     "return on capital employed"],
    "roe":          ["roe %", "roe", "return on equity %", "return on equity"],
    "sales_growth": ["sales growth %", "sales growth", "revenue growth %",
                     "revenue growth", "sales growth 3yr cagr %",
                     "sales growth 3yrs"],
    "debt_to_equity": ["debt / equity", "debt to equity", "d/e", "de ratio",
                        "debt/equity"],
    "market_cap":   ["market capitalization", "market cap", "mcap",
                     "market capitalization (cr)"],
    "pe_ratio":     ["p/e", "pe ratio", "pe", "price/earnings"],
    "sector":       ["sector"],
}


def _find_col(df_cols: list[str], variants: list[str]) -> Optional[str]:
    """Case-insensitive match of column name against variant list."""
    lower_cols = {c.lower().strip(): c for c in df_cols}
    for v in variants:
        if v in lower_cols:
            return lower_cols[v]
    return None


def _coerce_numeric(series: pd.Series) -> pd.Series:
    """Strip commas, '%', whitespace and coerce to float."""
    return (
        series.astype(str)
              .str.replace(",", "", regex=False)
              .str.replace("%", "", regex=False)
              .str.strip()
              .replace({"": None, "nan": None, "None": None, "-": None, "N/A": None})
              .pipe(pd.to_numeric, errors="coerce")
    )


def process_screener_csv(
    file_content: bytes | str,
    filename: str = "screener_export.csv",
) -> dict:
    """
    Parse a Screener.in CSV export, apply fundamental filters, and upsert
    results into pos_universe.

    Args:
        file_content: raw bytes or string content of the CSV file.
        filename:     original filename (used for logging only).

    Returns:
        {
            "total_rows": int,
            "passed": int,
            "failed": int,
            "tickers": list[str],
            "errors": list[str],
        }
    """
    errors: list[str] = []

    # Parse CSV
    try:
        if isinstance(file_content, bytes):
            df = pd.read_csv(io.BytesIO(file_content))
        else:
            df = pd.read_csv(io.StringIO(file_content))
    except Exception as e:
        return {"total_rows": 0, "passed": 0, "failed": 0, "tickers": [],
                "errors": [f"CSV parse failed: {e}"]}

    log.info("[universe] Loaded %d rows from %s — columns: %s",
             len(df), filename, list(df.columns))
    total_rows = len(df)

    # Map columns
    cols = list(df.columns)
    col_ticker = _find_col(cols, _COL_MAP["ticker"])
    col_name   = _find_col(cols, _COL_MAP["company_name"])
    col_roce   = _find_col(cols, _COL_MAP["roce"])
    col_roe    = _find_col(cols, _COL_MAP["roe"])
    col_sg     = _find_col(cols, _COL_MAP["sales_growth"])
    col_de     = _find_col(cols, _COL_MAP["debt_to_equity"])
    col_mcap   = _find_col(cols, _COL_MAP["market_cap"])
    col_pe     = _find_col(cols, _COL_MAP["pe_ratio"])
    col_sector = _find_col(cols, _COL_MAP["sector"])

    if col_ticker is None:
        return {"total_rows": total_rows, "passed": 0, "failed": total_rows,
                "tickers": [],
                "errors": [f"Ticker column not found. Columns: {cols}"]}

    # Build working frame
    work = pd.DataFrame()
    work["ticker"]  = df[col_ticker].astype(str).str.strip().str.upper()
    work["company_name"]    = df[col_name].astype(str).str.strip()  if col_name   else ""
    work["sector"]          = df[col_sector].astype(str).str.strip() if col_sector else ""
    work["roce"]            = _coerce_numeric(df[col_roce])    if col_roce else None
    work["roe"]             = _coerce_numeric(df[col_roe])     if col_roe  else None
    work["sales_growth"]    = _coerce_numeric(df[col_sg])      if col_sg   else None
    work["debt_to_equity"]  = _coerce_numeric(df[col_de])      if col_de   else None
    work["market_cap"]      = _coerce_numeric(df[col_mcap])    if col_mcap else None
    work["pe_ratio"]        = _coerce_numeric(df[col_pe])      if col_pe   else None

    # Drop rows without a ticker
    work = work[work["ticker"].str.len() > 0].copy()

    # Warn about missing filter columns
    missing_filter_cols = []
    if col_roce is None:   missing_filter_cols.append("ROCE")
    if col_roe  is None:   missing_filter_cols.append("ROE")
    if col_sg   is None:   missing_filter_cols.append("Sales Growth")
    if col_de   is None:   missing_filter_cols.append("Debt/Equity")
    if missing_filter_cols:
        errors.append(f"Missing filter columns: {missing_filter_cols}. "
                      "All stocks accepted as-is (no fundamental filter applied).")
        log.warning("[universe] Missing filter columns: %s", missing_filter_cols)

    # Apply fundamental filters
    passed_mask = pd.Series([True] * len(work), index=work.index)
    filter_reasons: dict[int, list[str]] = {}

    def _apply(mask_col: Optional[str], series_key: str,
               op: str, threshold: float, label: str):
        nonlocal passed_mask
        if series_key not in work.columns:
            return
        col_series = work[series_key]
        valid = col_series.notna()
        if op == ">=":
            fail = valid & (col_series < threshold)
        else:  # "<="
            fail = valid & (col_series > threshold)
        for idx in work.index[fail]:
            filter_reasons.setdefault(idx, []).append(label)
        passed_mask &= ~fail

    _apply(col_roce, "roce",           ">=", POSITIONAL_FUND_MIN_ROCE,        f"ROCE<{POSITIONAL_FUND_MIN_ROCE}%")
    _apply(col_roe,  "roe",            ">=", POSITIONAL_FUND_MIN_ROE,         f"ROE<{POSITIONAL_FUND_MIN_ROE}%")
    _apply(col_sg,   "sales_growth",   ">=", POSITIONAL_FUND_MIN_SALES_GROWTH, f"SalesGrowth<{POSITIONAL_FUND_MIN_SALES_GROWTH}%")
    _apply(col_de,   "debt_to_equity", "<=", POSITIONAL_FUND_MAX_DE,           f"D/E>{POSITIONAL_FUND_MAX_DE}")

    passed_df = work[passed_mask].copy()
    failed_df = work[~passed_mask].copy()

    now_ts = datetime.now(timezone.utc).isoformat()
    tickers_passed: list[str] = []

    try:
        from db.models import get_conn
        with get_conn() as conn:
            # Mark all existing as out-of-universe first
            conn.execute("UPDATE pos_universe SET in_universe=0")

            for _, row in passed_df.iterrows():
                ticker = row["ticker"]
                # Normalize: add .NS suffix if not present and looks like NSE symbol
                if not ticker.endswith((".NS", ".BO")):
                    ticker = ticker + ".NS"
                tickers_passed.append(ticker)
                conn.execute(
                    """INSERT INTO pos_universe
                       (ticker, company_name, sector, market_cap, roce, roe,
                        sales_growth, debt_to_equity, pe_ratio, imported_at, in_universe)
                       VALUES (?,?,?,?,?,?,?,?,?,?,1)
                       ON CONFLICT(ticker) DO UPDATE SET
                           company_name=excluded.company_name,
                           sector=excluded.sector,
                           market_cap=excluded.market_cap,
                           roce=excluded.roce,
                           roe=excluded.roe,
                           sales_growth=excluded.sales_growth,
                           debt_to_equity=excluded.debt_to_equity,
                           pe_ratio=excluded.pe_ratio,
                           imported_at=excluded.imported_at,
                           in_universe=1,
                           filter_reason=NULL""",
                    (ticker,
                     str(row.get("company_name") or ""),
                     str(row.get("sector") or ""),
                     row.get("market_cap"),
                     row.get("roce"),
                     row.get("roe"),
                     row.get("sales_growth"),
                     row.get("debt_to_equity"),
                     row.get("pe_ratio"),
                     now_ts),
                )

            # Record failed with reason
            for idx, row in failed_df.iterrows():
                ticker = row["ticker"]
                if not ticker.endswith((".NS", ".BO")):
                    ticker = ticker + ".NS"
                reason = "; ".join(filter_reasons.get(idx, ["filtered"]))
                conn.execute(
                    """INSERT INTO pos_universe
                       (ticker, company_name, sector, market_cap, roce, roe,
                        sales_growth, debt_to_equity, pe_ratio, imported_at,
                        in_universe, filter_reason)
                       VALUES (?,?,?,?,?,?,?,?,?,?,0,?)
                       ON CONFLICT(ticker) DO UPDATE SET
                           in_universe=0, filter_reason=excluded.filter_reason,
                           imported_at=excluded.imported_at""",
                    (ticker,
                     str(row.get("company_name") or ""),
                     str(row.get("sector") or ""),
                     row.get("market_cap"),
                     row.get("roce"),
                     row.get("roe"),
                     row.get("sales_growth"),
                     row.get("debt_to_equity"),
                     row.get("pe_ratio"),
                     now_ts, "; ".join(filter_reasons.get(idx, []))),
                )
    except Exception as e:
        errors.append(f"DB write failed: {e}")
        log.error("[universe] DB write failed: %s", e)

    log.info("[universe] CSV processed: total=%d passed=%d failed=%d",
             total_rows, len(tickers_passed), len(failed_df))
    return {
        "total_rows": total_rows,
        "passed": len(tickers_passed),
        "failed": len(failed_df),
        "tickers": tickers_passed,
        "errors": errors,
    }


def get_fundamental_universe() -> list[str]:
    """
    Return list of NSE tickers (with .NS suffix) from pos_universe
    where in_universe = 1. Falls back to empty list if DB is cold.
    """
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT ticker FROM pos_universe WHERE in_universe=1 ORDER BY ticker"
            ).fetchall()
        tickers = [r["ticker"] for r in rows]
        log.info("[universe] fundamental universe: %d tickers", len(tickers))
        return tickers
    except Exception as e:
        log.warning("[universe] get_fundamental_universe failed: %s", e)
        return []


def universe_stats() -> dict:
    """Summary stats for the dashboard."""
    try:
        from db.models import get_conn
        with get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM pos_universe"
            ).fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM pos_universe WHERE in_universe=1"
            ).fetchone()[0]
            latest = conn.execute(
                "SELECT imported_at FROM pos_universe ORDER BY imported_at DESC LIMIT 1"
            ).fetchone()
        imported_at = dict(latest)["imported_at"] if latest else None
        return {"total": total, "active": active, "last_import": imported_at}
    except Exception:
        return {"total": 0, "active": 0, "last_import": None}


def get_universe_df() -> pd.DataFrame:
    """Full pos_universe table as a DataFrame for the dashboard table."""
    try:
        from db.models import query_df
        return query_df(
            """SELECT ticker, company_name, sector, roce, roe, sales_growth,
                      debt_to_equity, market_cap, in_universe, filter_reason
               FROM pos_universe
               ORDER BY in_universe DESC, roce DESC"""
        )
    except Exception:
        return pd.DataFrame()

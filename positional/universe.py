"""
Fundamental Universe Manager — Screener.in CSV-based whitelist.

Two-track fundamental filtering (applied when the CSV is uploaded):

  Track A — Non-financial companies (manufacturing, IT, FMCG, pharma, etc.)
    ROCE         > 15%   (capital efficiency)
    ROE          > 15%   (equity returns)
    Sales Growth > 15%   (3-year revenue CAGR)
    Debt/Equity  < 1     (balance-sheet health)
    Market Cap   > 500 Cr

  Track B — Banks & NBFCs
    D/E and ROCE are excluded — leverage IS the business model for financials.
    ROE          > 15%   (profitability)
    Revenue/NII  > 15%   (growth — maps to Sales Growth column in CSV)
    Gross NPA    < 3%    (asset quality — primary bank health indicator)
    Net NPA      < 1%    (strict credit quality gate)
    Market Cap   > 500 Cr

  Detection: a stock is treated as a bank/NBFC if:
    - The Sector/Industry column contains a financial keyword, OR
    - The CSV has a non-null "Gross NPA" / "Net NPA" column for that row

Screener.in query to use (run two queries and combine the CSVs, OR use
the single OR-query below if your Screener account supports it):

  ── Query A (non-financial) ───────────────────────────────────────────
  Return on capital employed > 15 AND
  Return on equity > 15 AND
  Sales growth 3Years > 15 AND
  Debt to equity < 1 AND
  Market Capitalization > 500

  ── Query B (Banks & NBFCs) ───────────────────────────────────────────
  Return on equity > 15 AND
  Sales growth 3Years > 15 AND
  Gross NPA < 3 AND
  Net NPA < 1 AND
  Market Capitalization > 500

  ── Combined single query (if supported) ─────────────────────────────
  Market Capitalization > 500 AND
  Return on equity > 15 AND
  Sales growth 3Years > 15 AND
  (
    (Return on capital employed > 15 AND Debt to equity < 1)
    OR
    (Gross NPA < 3 AND Net NPA < 1)
  )

Upload workflow:
  1. Run query on screener.in → Export CSV
  2. Upload the CSV via the dashboard Positional tab → Universe Manager
  3. App auto-detects banks/NBFCs and applies Track B filters
  4. The resulting whitelist feeds the daily EOD scanner
"""
from __future__ import annotations

import difflib
import functools
import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from config import (
    POSITIONAL_BANK_MAX_GNPA,
    POSITIONAL_BANK_MAX_NNPA,
    POSITIONAL_BANK_MIN_ROE,
    POSITIONAL_BANK_MIN_SALES_GROWTH,
    POSITIONAL_FINANCIAL_SECTORS,
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
    "sector":       ["sector"],
    "industry":     ["industry"],
    "roce":         ["roce %", "roce", "return on capital employed %",
                     "return on capital employed"],
    "roe":          ["roe %", "roe", "return on equity %", "return on equity"],
    "sales_growth": ["sales var 3yrs %", "sales var 3yrs", "sales var 3years %",
                     "sales growth 3yr cagr %", "sales growth 3yrs",
                     "sales growth 3years", "sales growth %", "sales growth",
                     "revenue growth %", "revenue growth"],
    "debt_to_equity": ["debt / equity", "debt to equity", "d/e", "de ratio",
                       "debt/equity"],
    "gross_npa":    ["gross npa %", "gross npa", "gnpa %", "gnpa"],
    "net_npa":      ["net npa %", "net npa", "nnpa %", "nnpa"],
    "market_cap":   ["mar cap rs.cr.", "mar cap rs cr", "mar cap",
                     "market capitalization", "market cap", "mcap",
                     "market capitalization (cr)", "market cap (cr.)"],
    "pe_ratio":     ["p/e", "pe ratio", "pe", "price/earnings"],
}


def _find_col(df_cols: list[str], variants: list[str]) -> Optional[str]:
    lower_cols = {c.lower().strip(): c for c in df_cols}
    for v in variants:
        if v in lower_cols:
            return lower_cols[v]
    return None


_NSE_SUFFIX_RE = re.compile(
    r"\b(limited|ltd\.?|private|pvt\.?|incorporated|inc\.?|"
    r"corporation|corp\.?|company|co\.?|india|industries|"
    r"enterprises|solutions|technologies|tech|group|holdings?)\b",
    re.IGNORECASE,
)


def _clean_name(name: str) -> str:
    """Normalise a company name for fuzzy matching."""
    s = _NSE_SUFFIX_RE.sub("", name.upper())
    return re.sub(r"[^A-Z0-9 ]", " ", s).split()  # list of tokens


@functools.lru_cache(maxsize=1)
def _fetch_nse_symbol_map() -> dict:
    """
    Download NSE's public equity list and return {normalised_name: SYMBOL}.
    Cached for the process lifetime. Returns {} on any error.
    """
    try:
        import requests
        resp = requests.get(
            "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        nse_df = pd.read_csv(io.StringIO(resp.text))
        name_col = _find_col(list(nse_df.columns), ["name of company", "name"])
        sym_col  = _find_col(list(nse_df.columns), ["symbol"])
        if name_col is None or sym_col is None:
            return {}
        result = {}
        for _, row in nse_df.iterrows():
            sym  = str(row[sym_col]).strip().upper()
            raw  = str(row[name_col]).strip()
            key  = " ".join(_clean_name(raw))
            if key:
                result[key] = sym
        log.info("[universe] NSE symbol map loaded: %d entries", len(result))
        return result
    except Exception as e:
        log.warning("[universe] NSE equity list fetch failed: %s — "
                    "name→symbol lookup unavailable", e)
        return {}


def _resolve_name_to_symbol(name: str, nse_map: dict) -> Optional[str]:
    """
    Try to match a Screener.in company name to an NSE symbol.
    1. Exact normalised match.
    2. difflib closest match (cutoff 0.72).
    Returns None if no confident match.
    """
    if not nse_map:
        return None
    key = " ".join(_clean_name(name))
    if not key:
        return None
    if key in nse_map:
        return nse_map[key]
    matches = difflib.get_close_matches(key, nse_map.keys(), n=1, cutoff=0.72)
    if matches:
        return nse_map[matches[0]]
    return None


def _coerce_numeric(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
              .str.replace(",", "", regex=False)
              .str.replace("%", "", regex=False)
              .str.strip()
              .replace({"": None, "nan": None, "None": None, "-": None, "N/A": None})
              .pipe(pd.to_numeric, errors="coerce")
    )


def _is_financial(row: pd.Series) -> bool:
    """
    Return True if the row represents a bank or NBFC.
    Detection priority:
      1. Sector/industry column contains a financial keyword
      2. Gross NPA or Net NPA column has a non-null value
    """
    for col in ("sector", "industry"):
        val = str(row.get(col, "") or "").lower().strip()
        if any(kw in val for kw in POSITIONAL_FINANCIAL_SECTORS):
            return True
    # NPA columns present and non-null → financial company
    for col in ("gross_npa", "net_npa"):
        v = row.get(col)
        if v is not None and pd.notna(v):
            return True
    return False


def process_screener_csv(
    file_content: bytes | str,
    filename: str = "screener_export.csv",
) -> dict:
    """
    Parse a Screener.in CSV export, apply dual-track fundamental filters,
    and upsert results into pos_universe.

    Track A (non-financial): ROCE > 15, ROE > 15, SalesGrowth > 15, D/E < 1
    Track B (banks/NBFCs):   ROE > 15, SalesGrowth > 15, GrossNPA < 3, NetNPA < 1

    Returns: {total_rows, passed, failed, financial_count, tickers, errors}
    """
    errors: list[str] = []

    try:
        if isinstance(file_content, bytes):
            df = pd.read_csv(io.BytesIO(file_content))
        else:
            df = pd.read_csv(io.StringIO(file_content))
    except Exception as e:
        return {"total_rows": 0, "passed": 0, "failed": 0, "financial_count": 0,
                "tickers": [], "errors": [f"CSV parse failed: {e}"]}

    log.info("[universe] Loaded %d rows from %s — columns: %s",
             len(df), filename, list(df.columns))
    total_rows = len(df)

    cols = list(df.columns)
    col_ticker  = _find_col(cols, _COL_MAP["ticker"])
    col_name    = _find_col(cols, _COL_MAP["company_name"])
    col_sector  = _find_col(cols, _COL_MAP["sector"])
    col_industry= _find_col(cols, _COL_MAP["industry"])
    col_roce    = _find_col(cols, _COL_MAP["roce"])
    col_roe     = _find_col(cols, _COL_MAP["roe"])
    col_sg      = _find_col(cols, _COL_MAP["sales_growth"])
    col_de      = _find_col(cols, _COL_MAP["debt_to_equity"])
    col_gnpa    = _find_col(cols, _COL_MAP["gross_npa"])
    col_nnpa    = _find_col(cols, _COL_MAP["net_npa"])
    col_mcap    = _find_col(cols, _COL_MAP["market_cap"])
    col_pe      = _find_col(cols, _COL_MAP["pe_ratio"])

    # ── Ticker resolution ────────────────────────────────────────────────
    _name_to_sym: dict = {}   # populated if we need name-based lookup

    if col_ticker is None:
        if col_name is None:
            return {"total_rows": total_rows, "passed": 0, "failed": total_rows,
                    "financial_count": 0, "tickers": [],
                    "errors": ["Neither NSE Code/Symbol nor Name column found. "
                               f"Columns in CSV: {cols}"]}
        log.warning(
            "[universe] No NSE Code/Symbol column found in %s. "
            "Falling back to company-name → NSE symbol lookup via NSE equity list.",
            filename,
        )
        errors.append(
            "NSE Code/Symbol column not found in CSV. "
            "Resolving company names to NSE symbols automatically — "
            "unresolved names will be skipped. "
            "Tip: copy the 'NSE Code' column from Screener.in to avoid this."
        )
        log.info("[universe] Fetching NSE equity list for name→symbol mapping...")
        _name_to_sym = _fetch_nse_symbol_map()
        if not _name_to_sym:
            errors.append(
                "Could not download NSE equity list (network error or NSE unreachable). "
                "Please add the 'NSE Code' column to your Screener.in export manually."
            )
            return {"total_rows": total_rows, "passed": 0, "failed": total_rows,
                    "financial_count": 0, "tickers": [], "errors": errors}
        log.info("[universe] NSE symbol map ready (%d entries). Resolving %d names...",
                 len(_name_to_sym), total_rows)

    # Build working frame
    work = pd.DataFrame()
    if col_ticker is not None:
        work["ticker"] = df[col_ticker].astype(str).str.strip().str.upper()
    else:
        # Resolve company name → NSE symbol
        names = df[col_name].astype(str).str.strip()
        resolved, unresolved = [], []
        for nm in names:
            sym = _resolve_name_to_symbol(nm, _name_to_sym)
            if sym:
                resolved.append(sym)
            else:
                unresolved.append(nm)
                resolved.append("")
        work["ticker"] = resolved
        if unresolved:
            log.warning(
                "[universe] Could not resolve %d company names to NSE symbols: %s",
                len(unresolved), unresolved[:10],
            )
            errors.append(
                f"{len(unresolved)} company name(s) could not be matched to an NSE symbol "
                f"and will be excluded: {', '.join(unresolved[:5])}"
                + (" …" if len(unresolved) > 5 else "")
            )
    work["company_name"]   = df[col_name].astype(str).str.strip()     if col_name    else ""
    work["sector"]         = df[col_sector].astype(str).str.strip()   if col_sector  else ""
    work["industry"]       = df[col_industry].astype(str).str.strip() if col_industry else ""
    work["roce"]           = _coerce_numeric(df[col_roce])   if col_roce  else pd.Series([None] * len(df))
    work["roe"]            = _coerce_numeric(df[col_roe])    if col_roe   else pd.Series([None] * len(df))
    work["sales_growth"]   = _coerce_numeric(df[col_sg])    if col_sg    else pd.Series([None] * len(df))
    work["debt_to_equity"] = _coerce_numeric(df[col_de])    if col_de    else pd.Series([None] * len(df))
    work["gross_npa"]      = _coerce_numeric(df[col_gnpa])  if col_gnpa  else pd.Series([None] * len(df))
    work["net_npa"]        = _coerce_numeric(df[col_nnpa])  if col_nnpa  else pd.Series([None] * len(df))
    work["market_cap"]     = _coerce_numeric(df[col_mcap])  if col_mcap  else pd.Series([None] * len(df))
    work["pe_ratio"]       = _coerce_numeric(df[col_pe])    if col_pe    else pd.Series([None] * len(df))

    work = work[work["ticker"].str.len() > 0].copy()

    # Warn on missing columns
    if col_gnpa is None and col_nnpa is None:
        errors.append(
            "NPA columns (Gross NPA %, Net NPA %) not found in CSV. "
            "Banks & NBFCs will be detected by sector name only — "
            "NPA quality filter will not be applied to them."
        )

    # ── Apply filters row-by-row (dual-track logic) ───────────────────────
    passed_rows:  list[dict] = []
    failed_rows:  list[dict] = []
    financial_count = 0

    for idx, row in work.iterrows():
        is_fin = _is_financial(row)
        reasons: list[str] = []

        if is_fin:
            # ── Track B: Banks / NBFCs ────────────────────────────────────
            financial_count += 1
            roe = row.get("roe")
            sg  = row.get("sales_growth")
            gnpa= row.get("gross_npa")
            nnpa= row.get("net_npa")

            if roe  is not None and pd.notna(roe)  and roe  < POSITIONAL_BANK_MIN_ROE:
                reasons.append(f"ROE {roe:.1f}% < {POSITIONAL_BANK_MIN_ROE}%")
            if sg   is not None and pd.notna(sg)   and sg   < POSITIONAL_BANK_MIN_SALES_GROWTH:
                reasons.append(f"Growth {sg:.1f}% < {POSITIONAL_BANK_MIN_SALES_GROWTH}%")
            if gnpa is not None and pd.notna(gnpa) and gnpa > POSITIONAL_BANK_MAX_GNPA:
                reasons.append(f"GrossNPA {gnpa:.1f}% > {POSITIONAL_BANK_MAX_GNPA}%")
            if nnpa is not None and pd.notna(nnpa) and nnpa > POSITIONAL_BANK_MAX_NNPA:
                reasons.append(f"NetNPA {nnpa:.1f}% > {POSITIONAL_BANK_MAX_NNPA}%")
        else:
            # ── Track A: Non-financial companies ─────────────────────────
            roce = row.get("roce")
            roe  = row.get("roe")
            sg   = row.get("sales_growth")
            de   = row.get("debt_to_equity")

            if roce is not None and pd.notna(roce) and roce < POSITIONAL_FUND_MIN_ROCE:
                reasons.append(f"ROCE {roce:.1f}% < {POSITIONAL_FUND_MIN_ROCE}%")
            if roe  is not None and pd.notna(roe)  and roe  < POSITIONAL_FUND_MIN_ROE:
                reasons.append(f"ROE {roe:.1f}% < {POSITIONAL_FUND_MIN_ROE}%")
            if sg   is not None and pd.notna(sg)   and sg   < POSITIONAL_FUND_MIN_SALES_GROWTH:
                reasons.append(f"Growth {sg:.1f}% < {POSITIONAL_FUND_MIN_SALES_GROWTH}%")
            if de   is not None and pd.notna(de)   and de   > POSITIONAL_FUND_MAX_DE:
                reasons.append(f"D/E {de:.2f} > {POSITIONAL_FUND_MAX_DE}")

        row_dict = row.to_dict()
        row_dict["_is_financial"] = is_fin
        row_dict["_filter_reason"] = "; ".join(reasons) if reasons else None

        if reasons:
            failed_rows.append(row_dict)
        else:
            passed_rows.append(row_dict)

    # ── Persist to DB ─────────────────────────────────────────────────────
    now_ts = datetime.now(timezone.utc).isoformat()
    tickers_passed: list[str] = []

    try:
        from db.models import get_conn
        with get_conn() as conn:
            conn.execute("UPDATE pos_universe SET in_universe=0")

            for row in passed_rows:
                ticker = str(row["ticker"])
                if not ticker.endswith((".NS", ".BO")):
                    ticker += ".NS"
                tickers_passed.append(ticker)
                is_fin = row["_is_financial"]
                conn.execute(
                    """INSERT INTO pos_universe
                       (ticker, company_name, sector, market_cap, roce, roe,
                        sales_growth, debt_to_equity, pe_ratio, imported_at,
                        in_universe, filter_reason)
                       VALUES (?,?,?,?,?,?,?,?,?,?,1,NULL)
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
                     str(row.get("sector") or row.get("industry") or ""),
                     row.get("market_cap"),
                     row.get("roce"),
                     row.get("roe"),
                     row.get("sales_growth"),
                     row.get("debt_to_equity") if not is_fin else None,
                     row.get("pe_ratio"),
                     now_ts),
                )

            for row in failed_rows:
                ticker = str(row["ticker"])
                if not ticker.endswith((".NS", ".BO")):
                    ticker += ".NS"
                is_fin = row["_is_financial"]
                conn.execute(
                    """INSERT INTO pos_universe
                       (ticker, company_name, sector, market_cap, roce, roe,
                        sales_growth, debt_to_equity, pe_ratio, imported_at,
                        in_universe, filter_reason)
                       VALUES (?,?,?,?,?,?,?,?,?,?,0,?)
                       ON CONFLICT(ticker) DO UPDATE SET
                           in_universe=0,
                           filter_reason=excluded.filter_reason,
                           imported_at=excluded.imported_at""",
                    (ticker,
                     str(row.get("company_name") or ""),
                     str(row.get("sector") or row.get("industry") or ""),
                     row.get("market_cap"),
                     row.get("roce"),
                     row.get("roe"),
                     row.get("sales_growth"),
                     row.get("debt_to_equity") if not is_fin else None,
                     row.get("pe_ratio"),
                     now_ts,
                     row.get("_filter_reason")),
                )
    except Exception as e:
        errors.append(f"DB write failed: {e}")
        log.error("[universe] DB write failed: %s", e)

    non_fin_passed = sum(1 for r in passed_rows if not r["_is_financial"])
    fin_passed     = sum(1 for r in passed_rows if r["_is_financial"])

    log.info(
        "[universe] CSV processed: total=%d passed=%d (non-fin=%d banks/nbfc=%d) failed=%d",
        total_rows, len(passed_rows), non_fin_passed, fin_passed, len(failed_rows),
    )
    return {
        "total_rows":      total_rows,
        "passed":          len(tickers_passed),
        "failed":          len(failed_rows),
        "financial_count": financial_count,
        "fin_passed":      fin_passed,
        "tickers":         tickers_passed,
        "errors":          errors,
    }


def get_fundamental_universe() -> list[str]:
    """Return list of NSE tickers (with .NS) from pos_universe where in_universe=1."""
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
            total  = conn.execute("SELECT COUNT(*) FROM pos_universe").fetchone()[0]
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
               ORDER BY in_universe DESC, roe DESC"""
        )
    except Exception:
        return pd.DataFrame()

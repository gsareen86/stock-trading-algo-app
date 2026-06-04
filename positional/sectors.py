"""Shared sector helpers used by positional strategies.

Maps yfinance sector strings → NSE sector-index keys, and looks up a ticker's
sector from the fundamentals table. Lives here (rather than inside a strategy
module) so strategies can share it without importing each other.
"""
from __future__ import annotations

from typing import Dict, Optional

# yfinance sector string (lowercased) → NSE sector-index key (see SECTOR_INDEX_TICKERS)
SECTOR_MAP: Dict[str, str] = {
    "technology":                "IT",
    "information technology":    "IT",
    "consumer technology":       "IT",
    "financial services":        "Bank",
    "financial":                 "Bank",
    "banks":                     "Bank",
    "consumer defensive":        "FMCG",
    "consumer staples":          "FMCG",
    "healthcare":                "Pharma",
    "consumer cyclical":         "Auto",
    "basic materials":           "Metal",
    "energy":                    "Energy",
    "real estate":               "Realty",
}


def ticker_sector(ticker: str) -> Optional[str]:
    """Look up the ticker's (lowercased) sector from the fundamentals DB table."""
    try:
        from db.models import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT sector FROM fundamentals WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row and row["sector"]:
            return row["sector"].lower()
    except Exception:
        pass
    return None


def sector_key_for(ticker: str) -> Optional[str]:
    """Resolve a ticker to its NSE sector-index key, or None if unknown."""
    raw = ticker_sector(ticker)
    if not raw:
        return None
    for k, v in SECTOR_MAP.items():
        if k in raw:
            return v
    return None

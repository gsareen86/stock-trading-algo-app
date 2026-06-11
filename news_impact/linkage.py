"""Ticker -> sector resolution + universe membership for the news-impact
pipeline.

Sector precedence is **fundamentals.sector -> lt_universe.sector ->
pos_universe.sector** (first non-null wins). The three tables can disagree;
this resolves to a single canonical sector per ticker so SECTOR / ANCILLARY
linkage classification is deterministic.

All ticker comparisons go through :func:`bare` which strips trailing ``.NS``
/ ``.BO`` suffixes - the intraday ``positions`` table sometimes carries the
yfinance suffix while ``news.tickers``, ``fundamentals``, ``pos_positions``
and ``lt_universe`` use the bare NSE code.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)


def bare(ticker: str) -> str:
    """Strip ``.NS`` / ``.BO`` suffix. Returns the upper-cased bare code."""
    if not ticker:
        return ""
    t = ticker.strip().upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return t[:-3]
    return t


def _normalise_sector(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("none", "null", "nan", "—", "-"):
        return None
    return s


def build_ticker_sector_map() -> Dict[str, str]:
    """Return ``{bare_ticker: canonical_sector}`` for every ticker we know.

    Precedence per ticker:
      1. ``fundamentals.sector``
      2. ``lt_universe.sector``
      3. ``pos_universe.sector``

    Tickers with no usable sector in any source are absent from the map -
    downstream code interprets absence as "DIRECT-only candidate".
    """
    from db.models import get_conn

    out: Dict[str, str] = {}
    try:
        with get_conn() as conn:
            # pos_universe — lowest precedence, written first so later sources overwrite.
            for r in conn.execute(
                "SELECT ticker, sector FROM pos_universe WHERE sector IS NOT NULL"
            ).fetchall():
                sec = _normalise_sector(r["sector"])
                if sec:
                    out[bare(r["ticker"])] = sec
            for r in conn.execute(
                "SELECT ticker, sector FROM lt_universe WHERE sector IS NOT NULL"
            ).fetchall():
                sec = _normalise_sector(r["sector"])
                if sec:
                    out[bare(r["ticker"])] = sec
            # Highest precedence last.
            for r in conn.execute(
                "SELECT ticker, sector FROM fundamentals WHERE sector IS NOT NULL"
            ).fetchall():
                sec = _normalise_sector(r["sector"])
                if sec:
                    out[bare(r["ticker"])] = sec
    except Exception as e:
        log.warning("[news_impact.linkage] sector map build failed: %s", e)
    return out


def holdings_set() -> Set[str]:
    """Bare tickers currently held in the swing-positional book."""
    from db.models import get_conn
    out: Set[str] = set()
    try:
        with get_conn() as conn:
            for r in conn.execute(
                "SELECT DISTINCT ticker FROM pos_positions WHERE status='OPEN'"
            ).fetchall():
                out.add(bare(r["ticker"]))
    except Exception as e:
        log.warning("[news_impact.linkage] holdings_set failed: %s", e)
    return out


def scan_set() -> Set[str]:
    """Latest scan candidates (one row per ticker) — Swing + Long-Term
    candidates get news-impact coverage even before they are held."""
    out: Set[str] = set()
    try:
        from db.models import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT ticker FROM pos_scans
                   WHERE id IN (SELECT MAX(id) FROM pos_scans GROUP BY ticker)"""
            ).fetchall()
        out = {bare(r["ticker"]) for r in rows if r["ticker"]}
    except Exception:
        pass
    return out


def lt_set() -> Set[str]:
    """Bare tickers currently in the long-term watchlist."""
    from db.models import get_conn
    out: Set[str] = set()
    try:
        with get_conn() as conn:
            for r in conn.execute(
                "SELECT ticker FROM lt_universe WHERE in_universe=1"
            ).fetchall():
                out.add(bare(r["ticker"]))
    except Exception as e:
        log.warning("[news_impact.linkage] lt_set failed: %s", e)
    return out


def parse_tickers_csv(tickers_csv: Optional[str]) -> List[str]:
    """Split the ``news.tickers`` comma-string into a list of bare codes.

    Tokenises explicitly + strips suffix + upper-cases so a ``LIKE %LT%``
    style match never produces false positives between e.g. ``LT`` and
    ``LTIM``.
    """
    if not tickers_csv:
        return []
    out: List[str] = []
    for raw in str(tickers_csv).split(","):
        b = bare(raw)
        if b:
            out.append(b)
    return out


def classify_linkage(
    ticker: str,
    article_tickers: List[str],
    article_primary_sector: Optional[str],
    article_ancillary_sectors: List[str],
    ticker_sector: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(linkage, linkage_sector)`` for one (ticker, article) pair.

    Priority: DIRECT beats SECTOR beats ANCILLARY beats None.
      * DIRECT     when the article tags the ticker explicitly.
      * SECTOR     when the article's primary sector == ticker's sector.
      * ANCILLARY  when the ticker's sector is in the article's ancillary list.
      * None       no useful relationship - caller skips.

    ``ticker_sector`` may be None for tickers we couldn't resolve in
    :func:`build_ticker_sector_map`. Such tickers can still get DIRECT
    classification but never SECTOR / ANCILLARY (returns None).
    """
    b = bare(ticker)
    if b and b in article_tickers:
        return ("DIRECT", None)
    if not ticker_sector:
        return (None, None)
    primary = _normalise_sector(article_primary_sector)
    if primary and _sector_match(primary, ticker_sector):
        return ("SECTOR", primary)
    for anc in article_ancillary_sectors or []:
        if _sector_match(anc, ticker_sector):
            return ("ANCILLARY", anc)
    return (None, None)


# Normalized sector mapping dictionary (extensible)
SECTOR_NORMALIZATION_MAP: Dict[str, List[str]] = {
    "Auto OEM": [
        "auto oem", "auto", "automobile", "automobiles", "automotive", 
        "ev", "electric vehicle", "electric vehicles"
    ],
    "Banks": [
        "banks", "banking", "banks - private", "banks - public", 
        "financial services", "financial"
    ],
    "Finance & NBFC": [
        "nbfc", "finance", "non-banking financial company", "housing finance"
    ],
    "IT Services": [
        "it services", "software", "information technology", "technology", 
        "consumer technology"
    ],
    "Renewable Energy": [
        "renewable energy", "green energy", "solar", "wind energy", 
        "renewables", "clean energy"
    ],
    "Battery & Storage": [
        "battery and storage systems", "bass", "battery & storage", 
        "battery", "batteries", "energy storage"
    ],
    "FMCG": [
        "fmcg", "consumer defensive", "consumer staples", "staples"
    ],
    "Pharma": [
        "pharma", "pharmaceuticals", "healthcare", "medicine"
    ],
    "Metals & Mining": [
        "metals & mining", "metals", "metal", "mining", "steel", 
        "basic materials", "aluminum"
    ],
    "Energy": [
        "energy", "oil & gas", "power", "electricity"
    ],
    "Realty": [
        "realty", "real estate", "construction", "infrastructure"
    ],
}

# Compile reverse lookup dictionary for fast performance
_REVERSE_SECTOR_MAP: Dict[str, str] = {}
for _canonical, _aliases in SECTOR_NORMALIZATION_MAP.items():
    _REVERSE_SECTOR_MAP[_canonical.lower().strip()] = _canonical
    for _alias in _aliases:
        _REVERSE_SECTOR_MAP[_alias.lower().strip()] = _canonical

def normalize_sector(sector_name: Optional[str]) -> Optional[str]:
    """Resolve a raw sector name to a canonical sector.
    Falls back to a cleaned title-case version of the raw string if not explicitly mapped.
    """
    if not sector_name:
        return None
    cleaned = sector_name.lower().strip()
    
    # 1. Exact match on compiled reverse lookup map
    if cleaned in _REVERSE_SECTOR_MAP:
        return _REVERSE_SECTOR_MAP[cleaned]
        
    # 2. Check root splits (e.g. split on dash)
    root = cleaned.split(" - ")[0].strip()
    if root in _REVERSE_SECTOR_MAP:
        return _REVERSE_SECTOR_MAP[root]
        
    # Fallback to original strip representation
    return sector_name.strip()

def _sector_match(a: str, b: str) -> bool:
    """Loose sector matching based on normalised canonical sectors."""
    if not a or not b:
        return False
    norm_a = normalize_sector(a)
    norm_b = normalize_sector(b)
    if not norm_a or not norm_b:
        return False
    return norm_a.lower() == norm_b.lower()

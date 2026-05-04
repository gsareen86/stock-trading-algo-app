"""
Positional universe screener.

Filters the full NIFTY-500 / lt_universe to a positional-trade shortlist:
  1. Must be in lt_universe (in_universe = 1)
  2. lt_quality total_score ≥ POSITIONAL_MIN_QUALITY_SCORE
  3. FII holding ≥ POSITIONAL_MIN_FII_PCT  (institutional interest)
  4. Quality data not stale (scored within last 30 days)

If lt_quality is empty (cold start), falls back to the full lt_universe.
Returns a list of (ticker, quality_score, sector) tuples ready for the scanner.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Tuple

from config import (
    POSITIONAL_MIN_FII_PCT,
    POSITIONAL_MIN_QUALITY_SCORE,
)
from db.models import get_conn

log = logging.getLogger(__name__)

QUALITY_STALE_DAYS = 30


def get_positional_universe() -> List[Tuple[str, float, str]]:
    """
    Returns list of (ticker, quality_score, sector).
    Tickers are bare NSE symbols (no .NS suffix) — the fetcher adds it.
    """
    stale_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=QUALITY_STALE_DAYS)
    ).isoformat()

    sql = """
        SELECT u.ticker,
               COALESCE(q.total_score, 50.0) AS quality_score,
               COALESCE(u.sector, f.sector, 'Unknown') AS sector
        FROM lt_universe u
        LEFT JOIN lt_quality q ON q.ticker = u.ticker
        LEFT JOIN fundamentals f ON f.ticker = u.ticker
        WHERE u.in_universe = 1
          AND (q.total_score IS NULL OR q.total_score >= ?)
          AND (q.scored_at IS NULL OR q.scored_at >= ?)
          AND (u.fii_pct IS NULL OR u.fii_pct >= ?)
        ORDER BY COALESCE(q.total_score, 50.0) DESC
    """
    try:
        with get_conn() as conn:
            rows = conn.execute(
                sql,
                (POSITIONAL_MIN_QUALITY_SCORE, stale_cutoff, POSITIONAL_MIN_FII_PCT),
            ).fetchall()
        result = [(r["ticker"], float(r["quality_score"]), r["sector"] or "Unknown")
                  for r in rows]
        log.info("positional universe: %d tickers (quality>=%s, FII>=%s%%)",
                 len(result), POSITIONAL_MIN_QUALITY_SCORE, POSITIONAL_MIN_FII_PCT)
        return result
    except Exception as e:
        log.warning("positional screener query failed: %s", e)
        return _fallback_universe()


def _fallback_universe() -> List[Tuple[str, float, str]]:
    """Fallback to full lt_universe when quality scores aren't populated yet."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT ticker, sector FROM lt_universe WHERE in_universe = 1"
            ).fetchall()
        result = [(r["ticker"], 50.0, r["sector"] or "Unknown") for r in rows]
        log.info("positional screener fallback: %d tickers from lt_universe", len(result))
        return result
    except Exception as e:
        log.warning("positional screener fallback failed: %s", e)
        return _hardcoded_tier1()


def _hardcoded_tier1() -> List[Tuple[str, float, str]]:
    """Tier-1 hardcoded universe used only when DB is cold."""
    tier1 = [
        ("HDFCBANK", 80.0, "Bank"), ("ICICIBANK", 78.0, "Bank"),
        ("KOTAKBANK", 79.0, "Bank"), ("SBIN", 72.0, "Bank"),
        ("TCS", 85.0, "IT"), ("INFY", 83.0, "IT"),
        ("HCLTECH", 78.0, "IT"), ("WIPRO", 74.0, "IT"),
        ("RELIANCE", 76.0, "Energy"), ("HINDUNILVR", 82.0, "FMCG"),
        ("ITC", 74.0, "FMCG"), ("NESTLEIND", 86.0, "FMCG"),
        ("SUNPHARMA", 75.0, "Pharma"), ("DRREDDY", 73.0, "Pharma"),
        ("MARUTI", 77.0, "Auto"), ("BAJAJ-AUTO", 79.0, "Auto"),
        ("TATASTEEL", 68.0, "Metal"), ("JSWSTEEL", 69.0, "Metal"),
        ("LT", 76.0, "Infra"), ("NTPC", 70.0, "Energy"),
        ("BAJFINANCE", 80.0, "Bank"), ("TITAN", 81.0, "Consumer"),
        ("ASIANPAINT", 83.0, "Consumer"), ("PIDILITIND", 82.0, "Chemical"),
    ]
    log.info("positional screener: using hardcoded Tier-1 (%d tickers)", len(tier1))
    return tier1

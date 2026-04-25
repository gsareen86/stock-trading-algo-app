"""
RSS-based news scraper for Indian equities. Zero API fees.
Reads a set of financial-news RSS feeds, extracts the relevant articles,
matches tickers by symbol AND company name, and stores them into the
`news` table.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Iterable, List, Optional

import feedparser

from config import NEWS_SOURCES
from data.universe import load_universe
from db.models import get_conn

log = logging.getLogger(__name__)


# Company-name aliases for ticker matching. News articles almost never use
# the NSE symbol (e.g. "BALRAMCHIN") in headlines — they use the company
# name ("Balrampur Chini"). So we add a curated name→ticker map for the
# NIFTY-50-ish set. Additions welcome.
TICKER_NAME_ALIASES: dict[str, list[str]] = {
    "RELIANCE":   ["RELIANCE INDUSTRIES", "RELIANCE"],
    "TCS":        ["TATA CONSULTANCY SERVICES", "TCS"],
    "HDFCBANK":   ["HDFC BANK"],
    "INFY":       ["INFOSYS"],
    "ICICIBANK":  ["ICICI BANK"],
    "HINDUNILVR": ["HINDUSTAN UNILEVER", "HUL"],
    "ITC":        ["ITC LIMITED", "ITC LTD"],
    "LT":         ["LARSEN & TOUBRO", "LARSEN AND TOUBRO", "L&T"],
    "SBIN":       ["STATE BANK OF INDIA", "SBI"],
    "BHARTIARTL": ["BHARTI AIRTEL", "AIRTEL"],
    "KOTAKBANK":  ["KOTAK MAHINDRA BANK", "KOTAK BANK"],
    "AXISBANK":   ["AXIS BANK"],
    "BAJFINANCE": ["BAJAJ FINANCE"],
    "ASIANPAINT": ["ASIAN PAINTS"],
    "MARUTI":     ["MARUTI SUZUKI", "MARUTI"],
    "HCLTECH":    ["HCL TECHNOLOGIES", "HCL TECH"],
    "SUNPHARMA":  ["SUN PHARMACEUTICAL", "SUN PHARMA"],
    "WIPRO":      ["WIPRO"],
    "M&M":        ["MAHINDRA & MAHINDRA", "MAHINDRA AND MAHINDRA"],
    "ULTRACEMCO": ["ULTRATECH CEMENT"],
    "NESTLEIND":  ["NESTLE INDIA", "NESTLE"],
    "TITAN":      ["TITAN COMPANY", "TITAN"],
    "POWERGRID":  ["POWER GRID CORPORATION", "POWER GRID"],
    "NTPC":       ["NTPC"],
    "ONGC":       ["OIL AND NATURAL GAS", "ONGC"],
    "TATAMOTORS": ["TATA MOTORS"],
    "TATASTEEL":  ["TATA STEEL"],
    "JSWSTEEL":   ["JSW STEEL"],
    "COALINDIA":  ["COAL INDIA"],
    "ADANIENT":   ["ADANI ENTERPRISES"],
    "ADANIPORTS": ["ADANI PORTS", "ADANI PORT"],
    "BAJAJFINSV": ["BAJAJ FINSERV"],
    "TECHM":      ["TECH MAHINDRA"],
    "HDFCLIFE":   ["HDFC LIFE"],
    "SBILIFE":    ["SBI LIFE"],
    "BRITANNIA":  ["BRITANNIA INDUSTRIES", "BRITANNIA"],
    "CIPLA":      ["CIPLA"],
    "DRREDDY":    ["DR REDDY", "DR. REDDY"],
    "DIVISLAB":   ["DIVIS LABORATORIES", "DIVI'S LAB"],
    "EICHERMOT":  ["EICHER MOTORS"],
    "GRASIM":     ["GRASIM INDUSTRIES"],
    "HEROMOTOCO": ["HERO MOTOCORP", "HERO MOTORS"],
    "HINDALCO":   ["HINDALCO"],
    "INDUSINDBK": ["INDUSIND BANK"],
    "BAJAJ-AUTO": ["BAJAJ AUTO"],
    "APOLLOHOSP": ["APOLLO HOSPITALS"],
    "BPCL":       ["BHARAT PETROLEUM", "BPCL"],
    "UPL":        ["UPL LIMITED"],
    "TATACONSUM": ["TATA CONSUMER"],
    "LTIM":       ["LTIMINDTREE", "LTI MINDTREE"],
    "TVSMOTOR":   ["TVS MOTOR"],
    "VEDL":       ["VEDANTA"],
    "DLF":        ["DLF LIMITED"],
    "PIDILITIND": ["PIDILITE INDUSTRIES", "PIDILITE"],
    "HAVELLS":    ["HAVELLS INDIA", "HAVELLS"],
    "DMART":      ["AVENUE SUPERMARTS", "D-MART", "DMART"],
    "SIEMENS":    ["SIEMENS"],
    "BOSCHLTD":   ["BOSCH LIMITED", "BOSCH LTD"],
    "AMBUJACEM":  ["AMBUJA CEMENTS"],
    "BIOCON":     ["BIOCON"],
    "LUPIN":      ["LUPIN LIMITED", "LUPIN LTD"],
    "MARICO":     ["MARICO"],
    "DABUR":      ["DABUR INDIA", "DABUR"],
    "COLPAL":     ["COLGATE-PALMOLIVE", "COLGATE PALMOLIVE"],
    "BERGEPAINT": ["BERGER PAINTS"],
    "SRF":        ["SRF LIMITED"],
    "MUTHOOTFIN": ["MUTHOOT FINANCE"],
    "ICICIPRULI": ["ICICI PRUDENTIAL"],
    "GAIL":       ["GAIL INDIA", "GAIL (INDIA)"],
    "IOC":        ["INDIAN OIL", "IOCL"],
    "HINDPETRO":  ["HINDUSTAN PETROLEUM", "HPCL"],
    "ADANIGREEN": ["ADANI GREEN"],
    "NAUKRI":     ["INFO EDGE"],
    "ZOMATO":     ["ZOMATO"],
    "PAYTM":      ["PAYTM", "ONE97 COMMUNICATIONS"],
    "IRCTC":      ["IRCTC", "INDIAN RAILWAY CATERING"],
    "IRFC":       ["INDIAN RAILWAY FINANCE"],
    "POLICYBZR":  ["POLICYBAZAAR", "PB FINTECH"],
    "NYKAA":      ["NYKAA", "FSN E-COMMERCE"],
    "BALRAMCHIN": ["BALRAMPUR CHINI", "BALRAMPUR SUGAR"],
}


def _normalize_text(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _match_tickers(text: str, universe: Iterable[str]) -> List[str]:
    """Case-insensitive match of tickers against article text.

    Two passes:
      1. Whole-word match on the NSE symbol itself (RELIANCE, TCS, ...).
      2. Substring match on curated company-name aliases
         ("Balrampur Chini" -> BALRAMCHIN). News writers use company names,
         not ticker codes, so this pass is where most hits actually come from.
    """
    text_upper = text.upper()
    hits: set[str] = set()

    for sym in universe:
        # Pass 1: symbol match (whole-word, skip very short noisy symbols).
        if len(sym) >= 3 and re.search(rf"\b{re.escape(sym)}\b", text_upper):
            hits.add(sym)
            continue

        # Pass 2: alias match (plain substring — names are distinctive).
        aliases = TICKER_NAME_ALIASES.get(sym)
        if aliases:
            for alias in aliases:
                if alias in text_upper:
                    hits.add(sym)
                    break
    return sorted(hits)


def news_db_stats() -> dict:
    """Quick summary for the dashboard: total items, items last 24h,
    most recent ts. Used by the News tab."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM news").fetchone()["n"]
        last_24h = conn.execute(
            "SELECT COUNT(*) AS n FROM news WHERE datetime(ts) >= datetime('now','-24 hours')"
        ).fetchone()["n"]
        latest = conn.execute(
            "SELECT MAX(ts) AS ts FROM news"
        ).fetchone()["ts"]
        tagged = conn.execute(
            "SELECT COUNT(*) AS n FROM news WHERE tickers <> ''"
        ).fetchone()["n"]
    return dict(total=total, last_24h=last_24h, tagged=tagged, latest=latest)


def _parse_feed(source: str, url: str) -> list[dict]:
    """Parse a single RSS feed -> list of normalized article dicts."""
    try:
        parsed = feedparser.parse(url)
    except Exception as e:
        log.warning("feed parse failed (%s): %s", source, e)
        return []

    items = []
    for entry in parsed.entries:
        title = _normalize_text(entry.get("title", ""))
        summary = _normalize_text(entry.get("summary", entry.get("description", "")))
        link = entry.get("link", "")
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            ts = datetime(*published[:6], tzinfo=timezone.utc).isoformat()
        else:
            ts = datetime.utcnow().isoformat()
        if not title or not link:
            continue
        items.append(
            dict(ts=ts, source=source, title=title, summary=summary, url=link)
        )
    return items


def scrape_all(universe: Optional[list[str]] = None) -> int:
    """
    Scrape every configured source, match tickers, and persist.
    Returns count of *new* items inserted.
    """
    universe = universe or load_universe()
    inserted = 0
    with get_conn() as conn:
        for source, url in NEWS_SOURCES.items():
            for item in _parse_feed(source, url):
                combined = f"{item['title']} {item['summary']}"
                tickers = _match_tickers(combined, universe)
                if not tickers:
                    # Still store market-wide news (tickers blank) — useful for regime.
                    tickers_str = ""
                else:
                    tickers_str = ",".join(tickers)
                try:
                    cur = conn.execute(
                        """INSERT INTO news
                           (ts, source, title, summary, url, tickers, sentiment, processed)
                           VALUES (?, ?, ?, ?, ?, ?, NULL, 0)
                           ON CONFLICT (url) DO NOTHING""",
                        (
                            item["ts"],
                            item["source"],
                            item["title"],
                            item["summary"],
                            item["url"],
                            tickers_str,
                        ),
                    )
                    if cur.rowcount:
                        inserted += 1
                except Exception as e:
                    log.debug("insert news failed: %s", e)
    log.info("news scrape: %d new items", inserted)
    return inserted


def retag_existing_news(universe: Optional[list[str]] = None) -> int:
    """Re-run ticker matching against all existing news rows.

    Useful when TICKER_NAME_ALIASES is updated — old rows were saved with
    empty `tickers` columns because the old matcher only looked at the NSE
    symbol. Returns count of rows whose tags changed.
    """
    universe = universe or load_universe()
    updated = 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, summary, tickers FROM news"
        ).fetchall()
        for r in rows:
            combined = f"{r['title'] or ''} {r['summary'] or ''}"
            new_tags = ",".join(_match_tickers(combined, universe))
            if new_tags != (r["tickers"] or ""):
                conn.execute(
                    "UPDATE news SET tickers=? WHERE id=?",
                    (new_tags, r["id"]),
                )
                updated += 1
    log.info("retag: %d rows updated", updated)
    return updated


def recent_news_for_ticker(ticker: str, hours: int = 24, limit: int = 20) -> list[dict]:
    """Return the most recent news items referencing a ticker."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ts, source, title, summary, url, sentiment
                 FROM news
                WHERE tickers LIKE ?
                  AND datetime(ts) >= datetime('now', ?)
                ORDER BY ts DESC
                LIMIT ?""",
            (f"%{ticker}%", f"-{hours} hours", limit),
        ).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = scrape_all()
    print(f"Scraped {n} new items.")

"""Recent news for an instrument, from Indian financial RSS feeds.

Ported from the predecessor's RSS approach — no API fees, no keys. The genuinely valuable part
carried over is the **alias map**: headlines say "Balrampur Chini", never "BALRAMCHIN", so
matching on the NSE symbol alone finds almost nothing.

**Returns articles, not sentiment.** The predecessor scored sentiment inline and stored the
score, which made it untraceable and unversioned — re-running against a better model would
have silently rewritten history. Here, interpretation happens in a strategy or a narrative,
both of which are explicitly traceable.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.core.clock import now_utc
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

RESOURCES = Path(__file__).parent / "resources"
FEEDS_FILE = RESOURCES / "feeds.json"
ALIASES_FILE = RESOURCES / "ticker_aliases.json"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "NSE symbol, e.g. RELIANCE"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
        "hours": {
            "type": "integer",
            "minimum": 1,
            "maximum": 720,
            "default": 72,
            "description": "Only return articles published within this many hours",
        },
    },
    "required": ["symbol"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "publisher": {"type": "string"},
        "published_at": {"type": ["string", "null"]},
        "matched_on": {"type": "string", "description": "The alias or symbol that matched"},
    },
    required=["title", "publisher"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "symbol": {"type": "string"},
        "feeds_read": {"type": "integer"},
        "feeds_failed": {"type": "array", "items": {"type": "string"}},
    },
)


@lru_cache(maxsize=1)
def _feeds() -> tuple[tuple[str, str], ...]:
    payload = json.loads(FEEDS_FILE.read_text("utf-8"))
    return tuple((f["source"], f["url"]) for f in payload.get("feeds", []))


@lru_cache(maxsize=1)
def _aliases() -> dict[str, tuple[str, ...]]:
    payload = json.loads(ALIASES_FILE.read_text("utf-8"))
    return {k: tuple(v) for k, v in payload.get("aliases", {}).items()}


def match_terms(symbol: str) -> tuple[str, ...]:
    """Everything a headline might call this company, longest first.

    Longest-first so "HDFC BANK" wins over "HDFC" — the shorter term would otherwise attribute
    a bank story to the wrong instrument.
    """
    terms = {symbol, *(_aliases().get(symbol, ()))}
    return tuple(sorted(terms, key=len, reverse=True))


def _matches(text: str, terms: tuple[str, ...]) -> str | None:
    upper = re.sub(r"[^A-Z0-9& ]+", " ", text.upper())
    padded = f" {re.sub(r'  +', ' ', upper)} "
    for term in terms:
        if f" {term} " in padded:
            return term
    return None


def _default_parser(url: str):
    import feedparser

    return feedparser.parse(url)


def _entry_time(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def handle(arguments: dict, context: ToolContext) -> dict:
    symbol = arguments["symbol"].strip().upper()
    limit = int(arguments.get("limit", 20))
    hours = int(arguments.get("hours", 72))

    parser = context.fetchers.get("feed_parser", _default_parser)
    now = context.now() if context.now else now_utc()
    cutoff = now.timestamp() - hours * 3600
    terms = match_terms(symbol)

    items: list[dict] = []
    failed: list[str] = []
    read = 0

    for source, url in _feeds():
        try:
            parsed = parser(url)
        except Exception as exc:
            # One feed being down degrades coverage; it must not fail the call.
            log.debug("feed %s failed: %s", source, exc)
            failed.append(source)
            continue

        read += 1
        for entry in getattr(parsed, "entries", []) or []:
            title = (getattr(entry, "title", "") or "").strip()
            summary = (getattr(entry, "summary", "") or "").strip()
            link = (getattr(entry, "link", "") or "").strip()
            if not title or not link:
                continue

            matched = _matches(f"{title} {summary}", terms)
            if not matched:
                continue

            published = _entry_time(entry)
            if published and published.timestamp() < cutoff:
                continue

            items.append(
                {
                    "source_ref": link,
                    "observed_at": now.isoformat(),
                    "title": title,
                    "summary": summary[:600],
                    "publisher": source,
                    "published_at": published.isoformat() if published else None,
                    "matched_on": matched,
                }
            )

    items.sort(key=lambda i: i["published_at"] or "", reverse=True)
    return {
        "symbol": symbol,
        "feeds_read": read,
        "feeds_failed": failed,
        "items": items[:limit],
    }


TOOL = ToolManifest(
    name="news_research",
    version="1.0.0",
    summary=(
        "Fetches recent news articles mentioning a stock from Indian financial RSS feeds. Use "
        "when explaining an unexplained price move, or when recent coverage or sentiment "
        "around a company is in question. Returns articles, not a sentiment score."
    ),
    description=(
        "Reads seven Indian financial news feeds and returns articles mentioning the given "
        "NSE symbol, matched via a curated company-name alias map because headlines use "
        "company names rather than exchange symbols. Returns the articles themselves with "
        "links and timestamps — no sentiment, score or interpretation."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("news", "research", "rss"),
)

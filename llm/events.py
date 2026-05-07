"""
Earnings and corporate-action extraction from news.

yfinance's earnings calendar is unreliable for Indian stocks — it misses or
date-shifts ~20% of NSE results. The LLM reads recent news and extracts
upcoming events with structured fields, which the bot uses to:

  - Block intraday entries 1-2 days before earnings (gap risk)
  - Reduce size on the day of board meetings or AGM
  - Avoid fresh longs near record dates / corporate actions

Cached per (ticker, date) so we hit the API at most once per ticker per day.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from config import IST, LLM_EVENTS_MODEL
from llm.client import call_json

log = logging.getLogger(__name__)

EVENT_TYPES = (
    "earnings_release",
    "board_meeting",
    "dividend_record_date",
    "rights_issue",
    "qip",
    "agm",
    "bonus_issue",
    "stock_split",
    "buyback",
    "merger",
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(EVENT_TYPES)},
                    "date": {
                        "type": "string",
                        "description": "ISO date YYYY-MM-DD, or empty if unknown",
                    },
                    "confidence": {"type": "number"},
                    "headline": {"type": "string"},
                },
                "required": ["type", "date", "confidence", "headline"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You extract upcoming corporate-action and earnings events for Indian "
    "equities from raw news headlines. Only extract events confirmed by the "
    "headline text. Don't invent dates — if the date isn't in the article, "
    "leave it empty. Skip historical events (already happened). Return ONLY "
    "events in the next 14 days."
)


def extract_events(ticker: str, news_items: Iterable[dict]) -> Optional[list[dict]]:
    """Returns list of event dicts, or None on LLM failure.

    `news_items`: [{title, summary, ts}]. Cached by (ticker, today's date).
    """
    items = list(news_items)
    if not items:
        return []

    today = datetime.now(IST).date().isoformat()
    cache_key = f"events_{ticker}_{today}"

    headlines = "\n".join(
        f"- [{(n.get('ts') or '')[:10]}] {n.get('title', '')[:200]}"
        for n in items[:20]
    )
    prompt = (
        f"Ticker: {ticker}\n"
        f"Today: {today}\n\n"
        f"Recent news:\n{headlines}\n\n"
        "Output ONLY the JSON object."
    )
    return _call_with_cache(prompt, cache_key)


def _call_with_cache(prompt: str, cache_key: str) -> Optional[list[dict]]:
    result = call_json(
        prompt=prompt,
        schema=_SCHEMA,
        system=_SYSTEM,
        model=LLM_EVENTS_MODEL,
        max_tokens=600,
        cache_key=cache_key,
    )
    if result is None:
        return None
    return result.get("events", []) or []


def has_blocking_event(
    events: list[dict],
    *,
    side: str,           # "LONG" or "SHORT"
    days_ahead: int = 2,
    min_confidence: float = 0.7,
) -> Optional[str]:
    """If any event in the next `days_ahead` days blocks this trade, return
    a short reason; else None.

    Earnings releases block both sides (gap risk). Bonus / split / record
    dates block only LONG (ex-date drops the price). Buybacks & mergers are
    informational, not blocking.
    """
    if not events:
        return None
    today = datetime.now(IST).date()
    cutoff = today + timedelta(days=days_ahead)
    blocking_types = {"earnings_release", "board_meeting"}
    if side.upper() == "LONG":
        blocking_types |= {"dividend_record_date", "rights_issue", "qip"}

    for ev in events:
        if ev.get("type") not in blocking_types:
            continue
        if float(ev.get("confidence", 0)) < min_confidence:
            continue
        d_str = ev.get("date", "")
        if not d_str:
            continue
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        if today <= d <= cutoff:
            return f"{ev['type']} on {d_str}"
    return None

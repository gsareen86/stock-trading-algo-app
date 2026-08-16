"""Upcoming corporate events for an instrument.

Earnings dates and dividend actions are the events that most often invalidate a technical
setup — a breakout two days before results is a different proposition from the same breakout
two days after. This tool reports the dates; whether one blocks an entry is a gate, decided
in a strategy.

The provider lookup is injectable, so the tool is exercised offline against recorded
responses. Live verification needs a network this environment does not permit.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from app.core.clock import now_utc
from app.domain.instrument import Instrument
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

log = logging.getLogger(__name__)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "NSE symbol, e.g. RELIANCE"},
        "horizon_days": {"type": "integer", "minimum": 1, "maximum": 180, "default": 45},
    },
    "required": ["symbol"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "symbol": {"type": "string"},
        "event_type": {"type": "string", "enum": ["earnings", "dividend", "other"]},
        "event_date": {"type": "string", "description": "ISO date"},
        "days_away": {"type": "integer"},
        "detail": {"type": ["string", "null"]},
    },
    required=["symbol", "event_type", "event_date"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "symbol": {"type": "string"},
        "horizon_days": {"type": "integer"},
        "source_available": {"type": "boolean"},
    },
)


def _default_lookup(ticker: str) -> dict:
    """Provider calendar. Imported lazily so importing this module stays offline."""
    import yfinance as yf

    return dict(yf.Ticker(ticker).calendar or {})


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _classify(key: str) -> str:
    lowered = key.lower()
    if "earning" in lowered:
        return "earnings"
    if "dividend" in lowered or "ex-div" in lowered:
        return "dividend"
    return "other"


def handle(arguments: dict, context: ToolContext) -> dict:
    symbol = arguments["symbol"].strip().upper()
    horizon = int(arguments.get("horizon_days", 45))

    lookup = context.fetchers.get("calendar_lookup", _default_lookup)
    now = context.now() if context.now else now_utc()
    today = now.date()

    try:
        raw = lookup(Instrument(symbol).yf_ticker) or {}
        available = True
    except Exception as exc:
        # A provider outage yields no events, reported as such — not an empty list that reads
        # like "this company has nothing scheduled".
        log.debug("event calendar lookup failed for %s: %s", symbol, exc)
        raw, available = {}, False

    items = []
    for key, value in raw.items():
        candidates = value if isinstance(value, list | tuple) else [value]
        for candidate in candidates:
            event_date = _as_date(candidate)
            if event_date is None:
                continue
            days_away = (event_date - today).days
            if days_away < 0 or days_away > horizon:
                continue
            items.append(
                {
                    "source_ref": f"provider://calendar/{Instrument(symbol).yf_ticker}#{key}",
                    "observed_at": now.isoformat(),
                    "symbol": symbol,
                    "event_type": _classify(key),
                    "event_date": event_date.isoformat(),
                    "days_away": days_away,
                    "detail": str(key),
                }
            )

    items.sort(key=lambda i: i["event_date"])
    return {
        "symbol": symbol,
        "horizon_days": horizon,
        "source_available": available,
        "items": items,
    }


TOOL = ToolManifest(
    name="event_calendar",
    version="1.0.0",
    summary=(
        "Lists scheduled earnings and dividend events for a stock within a horizon. Use when "
        "checking what is due before entering or holding a position, or when a price move may "
        "be event-driven."
    ),
    description=(
        "Returns scheduled corporate events — earnings dates, dividend actions — for an NSE "
        "instrument within a given number of days. Reports whether the source was reachable, "
        "so 'no events scheduled' is distinguishable from 'could not ask'. Returns dates "
        "only; whether an upcoming event blocks an entry is a gate decided by a strategy."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("events", "earnings", "calendar"),
)

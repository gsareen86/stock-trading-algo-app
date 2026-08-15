"""Recent exchange announcements for an instrument.

Corporate announcements — board meetings, allotments, pledges, rating actions — are the
primary-source counterpart to news. A headline is somebody's summary; a filing is the thing
itself, which is why its `source_ref` is worth more to a narrative than an article link.

**Returns announcements, not materiality judgements.** Whether a pledge disclosure disqualifies
a candidate is a governance gate, decided deterministically in a strategy.

The fetcher is injectable; live verification needs a network this environment does not permit.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.clock import now_utc
from app.skills.evidence import item_schema, items_output_schema
from app.skills.types import SkillContext, SkillManifest

log = logging.getLogger(__name__)

#: NSE's announcements endpoint. Requires browser-like headers, like the constituent CSV.
NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "NSE symbol, e.g. RELIANCE"},
        "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 30},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
    },
    "required": ["symbol"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "symbol": {"type": "string"},
        "subject": {"type": "string"},
        "filed_at": {"type": ["string", "null"]},
        "category": {"type": ["string", "null"]},
    },
    required=["symbol", "subject"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "symbol": {"type": "string"},
        "days": {"type": "integer"},
        "source_available": {"type": "boolean"},
    },
)


def _default_fetcher(symbol: str) -> list[dict]:
    """Live NSE announcements. Imported lazily so this module imports offline."""
    import requests

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    response = requests.get(
        NSE_ANNOUNCEMENTS_URL,
        params={"index": "equities", "symbol": symbol},
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else payload.get("data", [])


def _parse_filed_at(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def handle(arguments: dict, context: SkillContext) -> dict:
    symbol = arguments["symbol"].strip().upper()
    days = int(arguments.get("days", 30))
    limit = int(arguments.get("limit", 20))

    fetcher = context.fetchers.get("announcements_fetcher", _default_fetcher)
    now = context.now() if context.now else now_utc()
    cutoff = now.timestamp() - days * 86400

    try:
        raw = fetcher(symbol) or []
        available = True
    except Exception as exc:
        log.debug("announcements fetch failed for %s: %s", symbol, exc)
        raw, available = [], False

    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        subject = (entry.get("desc") or entry.get("subject") or entry.get("sm_name") or "").strip()
        attachment = (entry.get("attchmntFile") or entry.get("attachment") or "").strip()
        if not subject:
            continue

        filed_at = _parse_filed_at(
            entry.get("an_dt") or entry.get("sort_date") or entry.get("date")
        )
        if filed_at and filed_at.timestamp() < cutoff:
            continue

        items.append(
            {
                # Prefer the attachment: it is the filing itself, not a summary of it.
                "source_ref": attachment or f"nse://announcement/{symbol}/{subject[:60]}",
                "observed_at": now.isoformat(),
                "symbol": symbol,
                "subject": subject[:500],
                "filed_at": filed_at.isoformat() if filed_at else None,
                "category": (entry.get("category") or entry.get("smIndustry") or None),
            }
        )

    items.sort(key=lambda i: i["filed_at"] or "", reverse=True)
    return {
        "symbol": symbol,
        "days": days,
        "source_available": available,
        "items": items[:limit],
    }


SKILL = SkillManifest(
    name="filings_scan",
    version="1.0.0",
    summary="List recent exchange announcements and filings for a stock.",
    description=(
        "Returns corporate announcements filed with NSE for an instrument within a recent "
        "window — board meetings, allotments, pledge disclosures, rating actions. Each item "
        "links to the filing itself where available, which is a stronger source for a "
        "narrative than a news summary of it. Reports whether the source was reachable, and "
        "makes no materiality judgement."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("filings", "announcements", "governance"),
)

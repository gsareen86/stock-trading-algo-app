"""Relative price performance against named peers.

Fundamentals were deferred to `screening-universe-and-gates`, so a fundamentals-backed
comparison cannot be built honestly yet. Price-based relative strength is genuinely useful in
its own right — Brahma-Vishnu-Mahesh ranks sectors on exactly this — and it is buildable now
on the `PriceSource` seam.

It also runs entirely offline, which makes it the skill that proves the whole registry path in
an environment where the other three cannot reach their sources.

**It measures; it does not rank.** No "winner", no score. A strategy decides what
outperformance means.
"""

from __future__ import annotations

from app.core.clock import now_utc
from app.data.fake import FakePriceSource
from app.skills.evidence import item_schema, items_output_schema
from app.skills.types import SkillContext, SkillManifest

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "NSE symbol of the subject, e.g. RELIANCE"},
        "peers": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "NSE symbols to compare against",
        },
        "lookback_days": {"type": "integer", "minimum": 5, "maximum": 400, "default": 90},
    },
    "required": ["symbol", "peers"],
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "symbol": {"type": "string"},
        "available": {"type": "boolean"},
        "return_pct": {"type": ["number", "null"]},
        "bars": {"type": "integer"},
        "relative_to_subject_pct": {"type": ["number", "null"]},
    },
    required=["symbol", "available"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "subject": {"type": "string"},
        "lookback_days": {"type": "integer"},
        "subject_return_pct": {"type": ["number", "null"]},
    },
)


def _window_return(series, lookback_days: int) -> tuple[float | None, int]:
    """Percent change across the lookback window, and how many bars backed it."""
    if series.is_empty:
        return None, 0
    frame = series.frame.tail(lookback_days)
    if len(frame) < 2:
        return None, len(frame)
    first = float(frame["close"].iloc[0])
    last = float(frame["close"].iloc[-1])
    if first == 0:
        return None, len(frame)
    return round((last / first - 1) * 100, 4), len(frame)


def handle(arguments: dict, context: SkillContext) -> dict:
    from app.domain.instrument import Instrument

    symbol = arguments["symbol"].strip().upper()
    peers = [p.strip().upper() for p in arguments["peers"]]
    lookback = int(arguments.get("lookback_days", 90))

    # A source is always injected in the platform; the fake keeps the skill runnable in
    # isolation rather than raising on a missing collaborator.
    source = context.price_source or FakePriceSource()
    observed_at = (context.now() if context.now else now_utc()).isoformat()

    subject_return, _ = _window_return(
        source.history(Instrument(symbol), lookback_days=max(lookback, 5)), lookback
    )

    items = []
    for peer in peers:
        series = source.history(Instrument(peer), lookback_days=max(lookback, 5))
        peer_return, bars = _window_return(series, lookback)
        available = peer_return is not None

        relative = None
        if available and subject_return is not None:
            relative = round(subject_return - peer_return, 4)

        items.append(
            {
                # No URL exists for a computed series, so the reference names the exact series
                # the number came from — which is what a reader needs to reproduce it.
                "source_ref": f"price://{peer}?interval=1d&lookback={lookback}",
                "observed_at": observed_at,
                "symbol": peer,
                # Reported rather than omitted: a peer silently missing from the comparison
                # would quietly change what the comparison means.
                "available": available,
                "return_pct": peer_return,
                "bars": bars,
                "relative_to_subject_pct": relative,
            }
        )

    return {
        "subject": symbol,
        "lookback_days": lookback,
        "subject_return_pct": subject_return,
        "items": items,
    }


SKILL = SkillManifest(
    name="peer_compare",
    version="1.0.0",
    summary="Compare a stock's recent price performance against named peers.",
    description=(
        "Computes percentage return over a lookback window for a subject instrument and each "
        "named peer, plus the subject's performance relative to each. Returns measurements "
        "only — deciding what outperformance means is a strategy's job. Peers with "
        "insufficient price history are reported as unavailable rather than dropped."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("prices", "comparison", "offline"),
)

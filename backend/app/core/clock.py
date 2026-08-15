"""Time handling.

**Storage is UTC; display and market logic are IST.** Indian market sessions, corporate
event dates and "as of" stamps are all IST concepts, but storing local times invites the
ambiguity that comes with any zone offset. So: one conversion boundary, applied here, and
naive datetimes are rejected rather than guessed at.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    """Current instant, timezone-aware, in UTC. The only clock read in the codebase."""
    return datetime.now(UTC)


def now_ist() -> datetime:
    """Current instant in IST, for market-session logic and display."""
    return now_utc().astimezone(IST)


def to_ist(moment: datetime) -> datetime:
    """Convert an aware datetime to IST.

    Raises on a naive datetime rather than assuming a zone — a silent assumption here
    would shift every market timestamp by 5h30m in a way nothing would catch.
    """
    if moment.tzinfo is None:
        raise ValueError("naive datetime: attach a timezone before converting to IST")
    return moment.astimezone(IST)


def to_utc(moment: datetime) -> datetime:
    """Convert an aware datetime to UTC for storage."""
    if moment.tzinfo is None:
        raise ValueError("naive datetime: attach a timezone before converting to UTC")
    return moment.astimezone(UTC)

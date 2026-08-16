"""Aggregating the call log.

Grouping happens **by IST day**, matching the market day the rest of the platform reasons
about — a call at 18:45 UTC belongs to the next IST day, and reporting it under the previous
one would put spend on a day the operator never worked.

The rollup is done in Python over a bounded window rather than in SQL. Date arithmetic in a
timezone the database was not asked to know about is dialect-specific and easy to get subtly
wrong, and this table sees a few thousand rows a month at most. Correctness and portability
beat a `GROUP BY` here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import IST, now_utc
from app.core.money import DEFAULT_USD_INR_RATE, usd_to_inr
from app.llm.types import CallStatus
from app.persistence.models import LlmCall

#: Window bounds for the usage endpoint. A year of rows would be a slow, useless response.
MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 7


@dataclass
class Bucket:
    """Totals for one grouping key."""

    calls: int = 0
    #: Calls whose provider reported a cost. The rest are local models, priced at nothing.
    priced_calls: int = 0
    unpriced_calls: int = 0
    failed_calls: int = 0
    spend_usd: float = 0.0
    total_tokens: int = 0

    def add(self, row: LlmCall) -> None:
        self.calls += 1
        if row.cost_usd is None:
            self.unpriced_calls += 1
        else:
            self.priced_calls += 1
            self.spend_usd += row.cost_usd
        if row.status not in (CallStatus.OK.value, CallStatus.CACHED.value):
            self.failed_calls += 1
        self.total_tokens += row.total_tokens or 0

    def as_dict(self, rate: float) -> dict:
        """Serialise for reporting, converting the accumulated dollars to rupees.

        Conversion happens here rather than in ``add`` so the sum is taken in the currency the
        amounts were billed in — converting each row first would round every one of them to
        paise and accumulate that error across the window.
        """
        return {
            "calls": self.calls,
            "priced_calls": self.priced_calls,
            # Surfaced explicitly: without it, spend looks like a total when it is only the
            # paid subset. Local calls are free, not missing.
            "unpriced_calls": self.unpriced_calls,
            "failed_calls": self.failed_calls,
            "spend_inr": usd_to_inr(self.spend_usd, rate),
            "total_tokens": self.total_tokens,
        }


@dataclass
class Usage:
    days: int
    totals: Bucket = field(default_factory=Bucket)
    by_day: dict[str, Bucket] = field(default_factory=dict)
    by_task: dict[str, Bucket] = field(default_factory=dict)
    by_provider: dict[str, Bucket] = field(default_factory=dict)

    def as_dict(self, rate: float) -> dict:
        return {
            "days": self.days,
            "totals": self.totals.as_dict(rate),
            "by_day": {
                k: v.as_dict(rate) for k, v in sorted(self.by_day.items(), reverse=True)
            },
            "by_task": {k: v.as_dict(rate) for k, v in sorted(self.by_task.items())},
            "by_provider": {k: v.as_dict(rate) for k, v in sorted(self.by_provider.items())},
        }


def _ist_day_key(moment) -> str:
    """IST calendar date of a stored timestamp, as ``YYYY-MM-DD``."""
    # SQLite hands back naive datetimes even for timezone-aware columns; they are stored as
    # UTC, so attaching UTC before converting is the correct reading, not a guess.
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(IST).date().isoformat()


def collect_usage(
    session_factory: sessionmaker[Session],
    days: int = DEFAULT_DAYS,
) -> Usage:
    """Roll up the last ``days`` IST days of calls."""
    usage = Usage(days=days)
    # Widen the fetch by a day on each side so rows near an IST boundary are not clipped by
    # a UTC-based cutoff before they can be attributed to the right IST day.
    since = now_utc() - timedelta(days=days + 1)
    cutoff = (now_utc().astimezone(IST).date() - timedelta(days=days - 1)).isoformat()

    with session_factory() as session:
        rows = session.execute(select(LlmCall).where(LlmCall.created_at >= since)).scalars()

        by_day: dict[str, Bucket] = defaultdict(Bucket)
        by_task: dict[str, Bucket] = defaultdict(Bucket)
        by_provider: dict[str, Bucket] = defaultdict(Bucket)

        for row in rows:
            day = _ist_day_key(row.created_at)
            if day < cutoff:
                continue
            usage.totals.add(row)
            by_day[day].add(row)
            by_task[row.task].add(row)
            by_provider[row.provider].add(row)

    usage.by_day = dict(by_day)
    usage.by_task = dict(by_task)
    usage.by_provider = dict(by_provider)
    return usage


def recent_calls(
    session_factory: sessionmaker[Session],
    limit: int = 50,
    rate: float = DEFAULT_USD_INR_RATE,
) -> list[dict]:
    """Most recent call records, newest first.

    Returns no prompt or completion text — this is a ledger, not a transcript.

    Each row carries both the stored dollar amount and its rupee equivalent: the first is
    what the vendor will invoice and what makes the row auditable, the second is what gets
    rendered. An unpriced local call is null in both — never zero in either.
    """
    with session_factory() as session:
        rows = (
            session.execute(select(LlmCall).order_by(LlmCall.id.desc()).limit(limit))
            .scalars()
            .all()
        )
        return [
            {
                "id": row.id,
                "created_at": (
                    row.created_at.replace(tzinfo=UTC)
                    if row.created_at.tzinfo is None
                    else row.created_at
                ).isoformat(),
                "task": row.task,
                "provider": row.provider,
                "model": row.model,
                "requested_model": row.requested_model,
                "used_fallback": row.used_fallback,
                "status": row.status,
                "total_tokens": row.total_tokens,
                "cost_usd": row.cost_usd,
                "cost_inr": usd_to_inr(row.cost_usd, rate),
                "latency_ms": row.latency_ms,
                "trace_id": row.trace_id,
                "error_msg": row.error_msg,
            }
            for row in rows
        ]

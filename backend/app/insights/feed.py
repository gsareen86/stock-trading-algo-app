"""Writing and reading the feed.

The only writer to `insights`. Deduplication happens here, on the way in, so a duplicate can
only come from a dedupe key being wrong rather than from two paths racing.

**Suppression is not deletion.** A suppressed candidate is simply not written; the original
insight stays in the feed with its original timestamp, which is what makes "this has been true
for eleven days" visible rather than making it look new every morning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now_utc
from app.insights.kinds import SEVERITY_ORDER, Kind, spec
from app.insights.rules import Candidate
from app.persistence.models import Insight as InsightRow

log = logging.getLogger(__name__)

#: A cycle producing more than this has something wrong with it, and truncating is a better
#: failure than flooding a feed people then learn to ignore.
MAX_PER_CYCLE = 12

MAX_PAGE = 200


@dataclass(frozen=True, slots=True)
class WriteReport:
    written: int
    suppressed: int
    truncated: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "written": self.written,
            "suppressed": self.suppressed,
            "truncated": self.truncated,
        }


class InsightFeed:
    """Records candidates and serves the feed."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    # ── writing ───────────────────────────────────────────────────────────────
    def record(
        self, candidates: list[Candidate], limit: int = MAX_PER_CYCLE
    ) -> WriteReport:
        """Write what is new, in severity order, up to the cap."""
        ordered = _by_severity(candidates)
        capped = ordered[:limit]
        truncated = len(ordered) - len(capped)

        written = 0
        suppressed = 0
        with self._sessions() as session:
            for candidate in capped:
                if self._is_suppressed(session, candidate):
                    suppressed += 1
                    continue
                session.add(
                    InsightRow(
                        kind=candidate.kind.value,
                        ticker=candidate.ticker,
                        title=candidate.title[:200],
                        body=candidate.body,
                        payload=candidate.payload,
                        dedupe_key=candidate.dedupe_key[:200],
                        severity=candidate.severity.value,
                    )
                )
                written += 1
            session.commit()

        return WriteReport(written=written, suppressed=suppressed, truncated=truncated)

    def _is_suppressed(self, session: Session, candidate: Candidate) -> bool:
        window = spec(candidate.kind).suppress_days
        if window <= 0:
            return False
        since = now_utc() - timedelta(days=window)
        found = session.execute(
            select(InsightRow.id)
            .where(
                InsightRow.dedupe_key == candidate.dedupe_key,
                InsightRow.created_at >= since,
            )
            .limit(1)
        ).first()
        return found is not None

    # ── reading ───────────────────────────────────────────────────────────────
    def recent(
        self,
        limit: int = 50,
        unread_only: bool = False,
        kind: Kind | None = None,
        ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._sessions() as session:
            stmt = select(InsightRow).order_by(InsightRow.created_at.desc(), InsightRow.id.desc())
            if unread_only:
                stmt = stmt.where(InsightRow.read_at.is_(None))
            if kind is not None:
                stmt = stmt.where(InsightRow.kind == kind.value)
            if ticker:
                stmt = stmt.where(InsightRow.ticker == ticker.strip().upper())
            rows = session.execute(stmt.limit(limit)).scalars().all()
            return [_to_dict(row) for row in rows]

    def unread_count(self) -> int:
        with self._sessions() as session:
            return int(
                session.execute(
                    select(func.count(InsightRow.id)).where(InsightRow.read_at.is_(None))
                ).scalar_one()
            )

    def mark_read(self, insight_id: int) -> bool:
        with self._sessions() as session:
            row = session.get(InsightRow, insight_id)
            if row is None:
                return False
            if row.read_at is None:
                row.read_at = now_utc()
                session.commit()
            return True

    def mark_all_read(self) -> int:
        with self._sessions() as session:
            rows = (
                session.execute(select(InsightRow).where(InsightRow.read_at.is_(None)))
                .scalars()
                .all()
            )
            stamp = now_utc()
            for row in rows:
                row.read_at = stamp
            session.commit()
            return len(rows)


def _by_severity(candidates: list[Candidate]) -> list[Candidate]:
    """High severity first, generation order within a band.

    Not "the most important N" — that would need a score comparable across kinds, which is a
    ranking, which is the thing this platform removed. Severity is a property of the kind.
    """
    ranked: list[Candidate] = []
    for level in SEVERITY_ORDER:
        ranked.extend(c for c in candidates if c.severity is level)
    return ranked


def _to_dict(row: InsightRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "severity": row.severity,
        "ticker": row.ticker,
        "title": row.title,
        "body": row.body,
        "payload": row.payload,
        "read": row.read_at is not None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

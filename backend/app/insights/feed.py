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
from app.insights.rules import Assessed, Candidate
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
    refreshed: int = 0
    withdrawn: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "written": self.written,
            "suppressed": self.suppressed,
            "truncated": self.truncated,
            "refreshed": self.refreshed,
            "withdrawn": self.withdrawn,
        }

    def merged_with(self, other: WriteReport) -> WriteReport:
        return WriteReport(
            written=self.written + other.written,
            suppressed=self.suppressed + other.suppressed,
            truncated=self.truncated + other.truncated,
            refreshed=self.refreshed + other.refreshed,
            withdrawn=self.withdrawn + other.withdrawn,
        )


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
                        # A freshly raised insight was measured when it was raised. Leaving
                        # this null would make a brand-new figure look unverified.
                        measured_at=now_utc(),
                    )
                )
                written += 1
            session.commit()

        return WriteReport(written=written, suppressed=suppressed, truncated=truncated)

    # ── reconciling ───────────────────────────────────────────────────────────
    def reconcile(
        self, candidates: list[Candidate], assessed: list[Assessed]
    ) -> WriteReport:
        """Bring standing insights into line with what this cycle just measured.

        Three outcomes, and the distinction between them is the whole point:

        * the subject was re-checked and still qualifies with the same figures — untouched;
        * still qualifies with different figures — **refreshed** in place, keeping its age and
          its read state, so "concentrated since the 17th" stays readable;
        * re-checked and no longer qualifies — **withdrawn**, with the reason recorded.

        Anything this cycle did not re-check is left exactly as it is. That is enforced by
        `assessed` rather than by inspecting the candidate list, because absence in the
        candidate list cannot distinguish "it ended" from "nobody looked".
        """
        live = {c.dedupe_key: c for c in candidates}
        coverage = {a.kind: a for a in assessed}
        refreshed = withdrawn = 0
        stamp = now_utc()

        with self._sessions() as session:
            standing = (
                session.execute(select(InsightRow).where(InsightRow.withdrawn_at.is_(None)))
                .scalars()
                .all()
            )

            for row in standing:
                try:
                    kind = Kind(row.kind)
                except ValueError:  # a kind retired since the row was written
                    continue

                cover = coverage.get(kind)
                if cover is None or not cover.covers(row.ticker):
                    continue

                candidate = live.get(row.dedupe_key)
                if candidate is None:
                    row.withdrawn_at = stamp
                    row.withdrawal_reason = cover.reason_for(row.ticker)
                    withdrawn += 1
                elif _figures_moved(row, candidate):
                    # Body and payload only. `created_at` is when this became true and
                    # `read_at` is whether it has been seen — a moved number changes neither.
                    row.title = candidate.title[:200]
                    row.body = candidate.body
                    row.payload = candidate.payload
                    row.measured_at = stamp
                    refreshed += 1
                else:
                    row.measured_at = stamp

            session.commit()

        return WriteReport(
            written=0, suppressed=0, truncated=0, refreshed=refreshed, withdrawn=withdrawn
        )

    def _is_suppressed(self, session: Session, candidate: Candidate) -> bool:
        """Whether this candidate is already on the feed, or too soon after it left it.

        Two questions, because a standing insight and a withdrawn one are different things:

        * **Standing** — the observation is already displayed, whatever its age. Writing a
          second row would put the same fact on the feed twice, and refreshing keeps the one
          that is there current, so age is no longer a reason to restate.
        * **Withdrawn** — the observation ended. If it recurs it is genuinely new, and the
          suppression window governs how soon it may be raised again, measured from when it
          ended rather than from when it first began.
        """
        standing = session.execute(
            select(InsightRow.id)
            .where(
                InsightRow.dedupe_key == candidate.dedupe_key,
                InsightRow.withdrawn_at.is_(None),
            )
            .limit(1)
        ).first()
        if standing is not None:
            return True

        window = spec(candidate.kind).suppress_days
        if window <= 0:
            return False
        since = now_utc() - timedelta(days=window)
        recently_ended = session.execute(
            select(InsightRow.id)
            .where(
                InsightRow.dedupe_key == candidate.dedupe_key,
                InsightRow.withdrawn_at >= since,
            )
            .limit(1)
        ).first()
        return recently_ended is not None

    # ── reading ───────────────────────────────────────────────────────────────
    def recent(
        self,
        limit: int = 50,
        unread_only: bool = False,
        kind: Kind | None = None,
        ticker: str | None = None,
        include_withdrawn: bool = False,
    ) -> list[dict[str, Any]]:
        with self._sessions() as session:
            stmt = select(InsightRow).order_by(InsightRow.created_at.desc(), InsightRow.id.desc())
            if not include_withdrawn:
                # Withdrawal is not deletion — the row stays, and asking for it returns it
                # with the reason. It just stops being something needing attention.
                stmt = stmt.where(InsightRow.withdrawn_at.is_(None))
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
                    select(func.count(InsightRow.id)).where(
                        InsightRow.read_at.is_(None), InsightRow.withdrawn_at.is_(None)
                    )
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
                session.execute(
                    select(InsightRow).where(
                        InsightRow.read_at.is_(None), InsightRow.withdrawn_at.is_(None)
                    )
                )
                .scalars()
                .all()
            )
            stamp = now_utc()
            for row in rows:
                row.read_at = stamp
            session.commit()
            return len(rows)


def _figures_moved(row: InsightRow, candidate: Candidate) -> bool:
    """Whether re-measuring the same observation produced different numbers.

    Compared on the rendered body and the structured payload together: the payload is what a
    reader can act on and the body is what they read, and a change to either is a change to
    what the feed is saying.
    """
    return row.body != candidate.body or (row.payload or {}) != (candidate.payload or {})


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
        # When the figures above were last established, as distinct from when this was first
        # raised. A reader deciding whether to act needs to know which they are looking at.
        "measured_at": row.measured_at.isoformat() if row.measured_at else None,
        "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
        "withdrawal_reason": row.withdrawal_reason,
    }

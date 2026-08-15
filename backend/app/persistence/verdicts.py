"""Storing verdicts.

No migration needed — `trading.verdicts` was created in `bootstrap-platform-skeleton` with
exactly these columns. That it fits unaltered is a small confirmation the decision model was
understood before the schema was written, rather than retrofitted onto it.
"""

from __future__ import annotations

import logging
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.verdict import Evidence, GateResult, Stance, Verdict
from app.persistence.models import Verdict as VerdictRow

log = logging.getLogger(__name__)

MAX_PAGE = 200


def _to_row(verdict: Verdict) -> VerdictRow:
    return VerdictRow(
        strategy_id=verdict.strategy_id,
        ticker=verdict.ticker,
        as_of=verdict.as_of,
        stance=verdict.stance.value,
        conviction=verdict.conviction,
        gates=verdict.gates_as_json(),
        evidence=verdict.evidence_as_json(),
        narrative=verdict.narrative,
        trace_id=verdict.trace_id,
    )


def _from_row(row: VerdictRow) -> Verdict:
    as_of = row.as_of if row.as_of.tzinfo else row.as_of.replace(tzinfo=UTC)
    return Verdict(
        strategy_id=row.strategy_id,
        ticker=row.ticker,
        as_of=as_of,
        stance=Stance(row.stance),
        conviction=row.conviction,
        evidence=tuple(Evidence.from_dict(e) for e in (row.evidence or [])),
        gates=tuple(GateResult.from_dict(g) for g in (row.gates or [])),
        narrative=row.narrative,
        trace_id=row.trace_id,
    )


class VerdictRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save_many(self, verdicts: list[Verdict]) -> int:
        """Persist verdicts, returning how many were written.

        Each verdict is stored whole — its own stance, conviction, gates and evidence. There
        is deliberately no upsert-by-ticker: two strategies disagreeing about one name is the
        normal case, and collapsing them would be the confluence scorecard again.
        """
        if not verdicts:
            return 0
        with self._session_factory() as session:
            session.add_all([_to_row(v) for v in verdicts])
            session.commit()
        return len(verdicts)

    def recent(
        self,
        ticker: str | None = None,
        strategy_id: str | None = None,
        limit: int = 50,
    ) -> list[Verdict]:
        limit = min(limit, MAX_PAGE)
        with self._session_factory() as session:
            statement = select(VerdictRow).order_by(VerdictRow.id.desc()).limit(limit)
            if ticker:
                statement = statement.where(VerdictRow.ticker == ticker.strip().upper())
            if strategy_id:
                statement = statement.where(VerdictRow.strategy_id == strategy_id)
            return [_from_row(row) for row in session.execute(statement).scalars().all()]

"""Recording themes, and deciding when one has stopped being true.

The only writer to the theme tables. Withdrawal lives here for the same reason it lives in
`insights.feed`: it is the operation that can do real damage, so it happens in one place under
one rule.

**That rule, learned the hard way in `feed-freshness-and-run-control`:** absence is not
evidence. A theme missing from a run's output can mean it faded, or that the sources which
evidenced it could not be read. Only the first is a withdrawal. So withdrawal is driven by
themes the run *positively assessed and found short* — never by what is missing from its
output — and a run that read nothing withdraws nothing.

Getting this wrong would be worse here than in the feed. A stale insight is visibly stale; a
theme withdrawn because a scrape failed simply disappears, and the reader has no way to know
they are looking at a market that went quiet rather than a downloader that broke.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now_utc
from app.domain.themes import Reference, SourceKind, Theme, ThemeEvidence
from app.persistence.models import ChainLink as ChainLinkRow
from app.persistence.models import Theme as ThemeRow
from app.persistence.models import ThemeCandidate as CandidateRow
from app.persistence.models import ThemeReference as ReferenceRow
from app.persistence.models import ThemeRun as RunRow

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: int
    surfaced: int
    refreshed: int
    withdrawn: int
    outcome: str
    sources_unavailable: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "surfaced": self.surfaced,
            "refreshed": self.refreshed,
            "withdrawn": self.withdrawn,
            "outcome": self.outcome,
            "sources_unavailable": list(self.sources_unavailable),
        }


class ThemeStore:
    """Persists runs, themes and their references."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    # ── runs ──────────────────────────────────────────────────────────────────
    def start_run(self, trigger: str = "requested") -> int:
        with self._sessions() as session:
            row = RunRow(trigger=trigger, outcome="running", sources_unavailable=[])
            session.add(row)
            session.commit()
            return row.id

    def running_run(self) -> int | None:
        """The run in progress, if any. A second concurrent run is refused, not queued."""
        with self._sessions() as session:
            found = session.execute(
                select(RunRow.id).where(RunRow.outcome == "running").limit(1)
            ).first()
            return found[0] if found else None

    def finish_run(
        self,
        run_id: int,
        outcome: str,
        sources_unavailable: tuple[str, ...] = (),
        documents_read: int = 0,
        reason: str | None = None,
    ) -> None:
        with self._sessions() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                return
            row.outcome = outcome
            row.sources_unavailable = list(sources_unavailable)
            row.documents_read = documents_read
            row.reason = reason
            row.finished_at = now_utc()
            session.commit()

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._sessions() as session:
            rows = (
                session.execute(
                    select(RunRow).order_by(RunRow.started_at.desc(), RunRow.id.desc()).limit(limit)
                )
                .scalars()
                .all()
            )
            return [_run_dict(r) for r in rows]

    # ── themes ────────────────────────────────────────────────────────────────
    def record(self, themes: list[Theme], measured_at: datetime | None = None) -> tuple[int, int]:
        """Write or refresh the themes a run surfaced. Returns ``(new, refreshed)``."""
        stamp = measured_at or now_utc()
        new = refreshed = 0

        with self._sessions() as session:
            for theme in themes:
                row = session.execute(
                    select(ThemeRow).where(ThemeRow.key == theme.key)
                ).scalar_one_or_none()
                counts = _counts(theme)

                if row is None:
                    session.add(
                        ThemeRow(key=theme.key, label=theme.label, measured_at=stamp, **counts)
                    )
                    new += 1
                else:
                    moved = any(getattr(row, field) != value for field, value in counts.items())
                    for field, value in counts.items():
                        setattr(row, field, value)
                    row.label = theme.label
                    row.measured_at = stamp
                    # A theme that faded and came back keeps its original first_seen_at and
                    # simply stands again — the record that it was once true is the point of
                    # not deleting it.
                    row.withdrawn_at = None
                    row.withdrawal_reason = None
                    refreshed += int(moved)

                self._record_references(session, theme)
            session.commit()

        return new, refreshed

    def _record_references(self, session: Session, theme: Theme) -> None:
        existing = {
            (r.symbol, r.period, r.source_ref)
            for r in session.execute(
                select(ReferenceRow).where(ReferenceRow.theme_key == theme.key)
            ).scalars()
        }
        for reference in theme.evidence.references:
            identity = (reference.symbol, reference.period, reference.source_ref)
            if identity in existing:
                continue
            existing.add(identity)
            session.add(
                ReferenceRow(
                    theme_key=theme.key,
                    symbol=reference.symbol,
                    period=reference.period,
                    kind=reference.kind.value,
                    source_ref=reference.source_ref[:500],
                    sector=reference.sector,
                    excerpt=(reference.excerpt or None),
                )
            )

    def withdraw_short(self, short_themes: list[Theme], shortfall) -> int:
        """Withdraw standing themes this run assessed and found below threshold.

        Driven by what was *assessed*, never by what is missing. A theme absent from both the
        surfaced and the short list was not looked at by this run — because its sources could
        not be read — and is left exactly as it is.
        """
        if not short_themes:
            return 0

        stamp = now_utc()
        withdrawn = 0
        with self._sessions() as session:
            for theme in short_themes:
                row = session.execute(
                    select(ThemeRow).where(
                        ThemeRow.key == theme.key, ThemeRow.withdrawn_at.is_(None)
                    )
                ).scalar_one_or_none()
                if row is None:
                    continue
                row.withdrawn_at = stamp
                row.withdrawal_reason = shortfall(theme.evidence)
                row.measured_at = stamp
                withdrawn += 1
            session.commit()
        return withdrawn

    def standing(self, include_withdrawn: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        with self._sessions() as session:
            statement = select(ThemeRow).order_by(
                ThemeRow.breadth.desc(), ThemeRow.persistence.desc(), ThemeRow.key
            )
            if not include_withdrawn:
                statement = statement.where(ThemeRow.withdrawn_at.is_(None))
            rows = session.execute(statement.limit(limit)).scalars().all()
            return [_theme_dict(r) for r in rows]

    def references(self, theme_key: str) -> list[Reference]:
        with self._sessions() as session:
            rows = (
                session.execute(
                    select(ReferenceRow).where(ReferenceRow.theme_key == theme_key)
                )
                .scalars()
                .all()
            )
            return [
                Reference(
                    symbol=r.symbol,
                    concept=r.theme_key,
                    period=r.period,
                    kind=SourceKind(r.kind),
                    source_ref=r.source_ref,
                    sector=r.sector,
                    excerpt=r.excerpt or "",
                )
                for r in rows
            ]

    def load(self, theme_key: str) -> Theme | None:
        """A stored theme with its references, for re-assessing it against a later run."""
        with self._sessions() as session:
            row = session.execute(
                select(ThemeRow).where(ThemeRow.key == theme_key)
            ).scalar_one_or_none()
            if row is None:
                return None
        return Theme(
            key=row.key,
            label=row.label,
            evidence=ThemeEvidence(references=tuple(self.references(theme_key))),
            first_seen=row.first_seen_at,
            withdrawn_at=row.withdrawn_at,
            withdrawal_reason=row.withdrawal_reason,
        )


    # ── chains and candidates ─────────────────────────────────────────────────
    def record_chain(self, theme_key: str, tiers: list[dict[str, Any]]) -> tuple[int, int]:
        """Write a theme's tiers, preserving any a reader has already rejected.

        Returns ``(written, preserved_rejections)``. A rejected link is never quietly
        reinstated by a later expansion — that is what makes rejecting one worth doing. Its
        reasoning is refreshed so the reader can see what the model said this time, but the
        rejection stands until they lift it.
        """
        written = preserved = 0
        with self._sessions() as session:
            for tier in tiers:
                label = str(tier.get("label") or "").strip()
                if not label:
                    continue
                row = session.execute(
                    select(ChainLinkRow).where(
                        ChainLinkRow.theme_key == theme_key,
                        ChainLinkRow.tier == int(tier.get("tier", 1)),
                        ChainLinkRow.label == label,
                    )
                ).scalar_one_or_none()

                if row is None:
                    session.add(
                        ChainLinkRow(
                            theme_key=theme_key,
                            tier=int(tier.get("tier", 1)),
                            label=label,
                            supplies=tier.get("supplies"),
                            reasoning=str(tier.get("reasoning") or ""),
                            proposed_by=str(tier.get("proposed_by") or "unknown"),
                            supplier_descriptions=list(tier.get("supplier_descriptions") or []),
                        )
                    )
                    written += 1
                else:
                    row.reasoning = str(tier.get("reasoning") or row.reasoning)
                    row.supplies = tier.get("supplies") or row.supplies
                    row.supplier_descriptions = list(tier.get("supplier_descriptions") or [])
                    row.proposed_by = str(tier.get("proposed_by") or row.proposed_by)
                    preserved += int(row.rejected_at is not None)
            session.commit()
        return written, preserved

    def chain(self, theme_key: str) -> list[dict[str, Any]]:
        with self._sessions() as session:
            rows = (
                session.execute(
                    select(ChainLinkRow)
                    .where(ChainLinkRow.theme_key == theme_key)
                    .order_by(ChainLinkRow.tier, ChainLinkRow.label)
                )
                .scalars()
                .all()
            )
            return [_link_dict(r) for r in rows]

    def reject_link(self, link_id: int, reason: str | None = None) -> bool:
        """Reject one link. Writes no trade and touches no position."""
        with self._sessions() as session:
            row = session.get(ChainLinkRow, link_id)
            if row is None:
                return False
            row.rejected_at = now_utc()
            row.rejected_reason = reason
            session.commit()
            return True

    def record_candidates(self, candidates: list) -> int:
        written = 0
        with self._sessions() as session:
            for candidate in candidates:
                exists = session.execute(
                    select(CandidateRow.id).where(
                        CandidateRow.theme_key == candidate.theme_key,
                        CandidateRow.tier == candidate.tier,
                        CandidateRow.symbol == candidate.symbol,
                    )
                ).first()
                if exists:
                    continue
                session.add(
                    CandidateRow(
                        theme_key=candidate.theme_key,
                        tier=candidate.tier,
                        symbol=candidate.symbol,
                        exposure=candidate.exposure.value,
                        exposure_basis=candidate.exposure_basis,
                        matched_description=candidate.matched_description,
                    )
                )
                written += 1
            session.commit()
        return written

    def candidates(self, theme_key: str) -> list[dict[str, Any]]:
        with self._sessions() as session:
            rows = (
                session.execute(
                    select(CandidateRow)
                    .where(CandidateRow.theme_key == theme_key)
                    .order_by(CandidateRow.tier, CandidateRow.symbol)
                )
                .scalars()
                .all()
            )
            return [
                {
                    "id": r.id,
                    "theme_key": r.theme_key,
                    "tier": r.tier,
                    "symbol": r.symbol,
                    "exposure": r.exposure,
                    "exposure_basis": r.exposure_basis,
                    "matched_description": r.matched_description,
                }
                for r in rows
            ]


def _link_dict(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "theme_key": row.theme_key,
        "tier": row.tier,
        "label": row.label,
        "supplies": row.supplies,
        "reasoning": row.reasoning,
        "proposed_by": row.proposed_by,
        "supplier_descriptions": list(row.supplier_descriptions or []),
        "rejected": row.rejected_at is not None,
        "rejected_reason": row.rejected_reason,
        # Never a platform measurement, carried so nothing downstream has to infer it.
        "measured_by_platform": False,
    }


def _counts(theme: Theme) -> dict[str, Any]:
    evidence = theme.evidence
    return {
        "breadth": evidence.breadth,
        "persistence": evidence.persistence,
        "sector_count": len(evidence.sectors),
        "source_kinds": sorted(k.value for k in evidence.source_kinds),
    }


def _theme_dict(row: ThemeRow) -> dict[str, Any]:
    return {
        "key": row.key,
        "label": row.label,
        "breadth": row.breadth,
        "persistence": row.persistence,
        "sector_count": row.sector_count,
        "source_kinds": list(row.source_kinds or []),
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "measured_at": row.measured_at.isoformat() if row.measured_at else None,
        "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
        "withdrawal_reason": row.withdrawal_reason,
    }


def _run_dict(row: RunRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "trigger": row.trigger,
        "outcome": row.outcome,
        "sources_unavailable": list(row.sources_unavailable or []),
        "documents_read": row.documents_read,
        "reason": row.reason,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }

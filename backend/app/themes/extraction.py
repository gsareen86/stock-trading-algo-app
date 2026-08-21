"""Holding what was read, and what it was decided to mean.

The store that lets an open vocabulary and stable counting coexist. Extraction is a model call
and answers differently every time; counting needs the same corpus to yield the same numbers.
Writing the extraction down resolves that — a document is read once, and every later run counts
over rows rather than over a fresh opinion.

Placement is stored apart from extraction on purpose. Reading is slow and settled; merging is
cheap and revisable, and a reader may reject a merge. Keeping them separate means a re-merge
never costs a re-read, and a rejected placement is a fact about the merge rather than a reason
to throw away the reading.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now_utc
from app.domain.themes import Reference, SourceKind
from app.persistence.models import ConceptPlacement as PlacementRow
from app.persistence.models import DocumentConcept as ConceptRow

log = logging.getLogger(__name__)


class ConceptStore:
    """Persists document extractions and the placements that turn them into themes."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    # ── extraction ────────────────────────────────────────────────────────────
    def has_read(self, source_ref: str) -> bool:
        """Whether a document has already been extracted.

        The check that keeps a weekly run affordable: reading is minutes of local model time
        per document, and a document does not change once published.
        """
        with self._sessions() as session:
            found = session.execute(
                select(ConceptRow.id).where(ConceptRow.source_ref == source_ref).limit(1)
            ).first()
            return found is not None

    def record(self, concepts: list[dict[str, Any]]) -> int:
        """Store what a model read. Returns how many rows were new."""
        written = 0
        with self._sessions() as session:
            for concept in concepts:
                label = (concept.get("label") or "").strip().lower()
                source_ref = (concept.get("source_ref") or "").strip()
                if not label or not source_ref:
                    continue

                exists = session.execute(
                    select(ConceptRow.id).where(
                        ConceptRow.source_ref == source_ref, ConceptRow.label == label
                    )
                ).first()
                if exists:
                    continue

                session.add(
                    ConceptRow(
                        symbol=(concept.get("symbol") or "").strip().upper(),
                        period=(concept.get("period") or "").strip(),
                        label=label[:200],
                        excerpt=(concept.get("excerpt") or None),
                        kind=(concept.get("kind") or SourceKind.COMMENTARY.value),
                        sector=concept.get("sector"),
                        source_ref=source_ref[:500],
                        extracted_by=(concept.get("extracted_by") or "")[:128],
                    )
                )
                written += 1
            session.commit()
        return written

    def labels(self, placed: bool | None = None) -> list[str]:
        """Distinct concept labels, optionally only those already placed or not yet placed."""
        with self._sessions() as session:
            all_labels = {
                row[0]
                for row in session.execute(select(ConceptRow.label).distinct()).all()
            }
            if placed is None:
                return sorted(all_labels)
            known = {
                row[0] for row in session.execute(select(PlacementRow.label).distinct()).all()
            }
            return sorted(all_labels & known if placed else all_labels - known)

    # ── placement ─────────────────────────────────────────────────────────────
    def place(self, placements: list[dict[str, Any]]) -> tuple[int, int]:
        """Record merge decisions. Returns ``(written, skipped_because_rejected)``."""
        written = rejected = 0
        with self._sessions() as session:
            for placement in placements:
                label = (placement.get("concept") or "").strip().lower()
                theme_key = (placement.get("theme") or "").strip().lower()
                if not label or not theme_key:
                    continue

                row = session.execute(
                    select(PlacementRow).where(PlacementRow.label == label)
                ).scalar_one_or_none()

                if row is not None and row.rejected_at is not None:
                    # Somebody threw this merge out. A later run proposing it again does not
                    # get to reinstate it silently.
                    rejected += 1
                    continue

                if row is None:
                    session.add(
                        PlacementRow(
                            label=label[:200],
                            theme_key=theme_key[:200],
                            reasoning=(placement.get("reasoning") or None),
                            decided_by=(placement.get("decided_by") or "")[:128],
                        )
                    )
                    written += 1
                elif row.theme_key != theme_key:
                    row.theme_key = theme_key[:200]
                    row.reasoning = placement.get("reasoning") or row.reasoning
                    row.decided_by = (placement.get("decided_by") or row.decided_by)[:128]
                    written += 1
            session.commit()
        return written, rejected

    def reject_placement(self, label: str) -> bool:
        """Reject a merge. The concept falls back to standing as its own theme."""
        with self._sessions() as session:
            row = session.execute(
                select(PlacementRow).where(PlacementRow.label == label.strip().lower())
            ).scalar_one_or_none()
            if row is None:
                return False
            row.rejected_at = now_utc()
            session.commit()
            return True

    def placements(self) -> dict[str, str]:
        """Label to theme key, ignoring rejected merges."""
        with self._sessions() as session:
            rows = (
                session.execute(
                    select(PlacementRow).where(PlacementRow.rejected_at.is_(None))
                )
                .scalars()
                .all()
            )
            return {row.label: row.theme_key for row in rows}

    # ── reading back as references ────────────────────────────────────────────
    def references(self) -> list[Reference]:
        """Every stored extraction, as a reference keyed by the theme it was placed on.

        An unplaced concept stands as its own theme. That is the conservative reading and it
        matters: dropping unplaced concepts would silently lose every theme the merge step
        failed to reach, and a merge failure would look like a quiet market.
        """
        placements = self.placements()
        with self._sessions() as session:
            rows = session.execute(select(ConceptRow)).scalars().all()

        return [
            Reference(
                symbol=row.symbol,
                concept=placements.get(row.label, row.label),
                period=row.period,
                kind=_kind(row.kind),
                source_ref=row.source_ref,
                sector=row.sector,
                excerpt=row.excerpt or "",
            )
            for row in rows
        ]


def _kind(value: str) -> SourceKind:
    try:
        return SourceKind(value)
    except ValueError:
        return SourceKind.COMMENTARY

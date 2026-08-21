"""Deciding what counts as a theme.

**Counting, not comprehension.** Whether a document describes a data-centre buildout is a
reading question and a model answers it — that lives in `concept_extract`. Whether enough
companies have said it for long enough to be a theme is arithmetic, and it lives here.

The division matters because the two fail differently. A model asked "what themes are emerging
in India" answers fluently whether or not anything is, and the answer changes between runs. But
*three companies across two sectors in two periods* is a claim that can be checked and can be
wrong — and it is only checkable because extraction is written down and counted rather than
re-formed on every run.

This module previously did the reading too, by matching ten hardcoded phrase groups. That could
only surface themes somebody had already typed in, which is a strange property for the part of
a platform whose whole job is noticing what you had not thought of. The reading moved to a
model; the counting stayed here, unchanged.

Nothing in this module calls a model, and nothing in it produces a score. Given the same
references it produces the same themes, in the same order, forever.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.themes import Reference, Theme, ThemeEvidence

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Thresholds:
    """What a concept must clear to be called a theme.

    Both, not either. Broad-but-fleeting is a news cycle — every company commenting on one
    budget announcement in one quarter. Persistent-but-narrow is one company's pet project.
    Neither is a theme, and requiring both is what separates a theme from a loud month.
    """

    #: Distinct companies that must reference it.
    min_companies: int = 3
    #: Distinct periods it must appear in.
    min_periods: int = 2
    #: Distinct sectors. A chain crosses sectors — that is the whole point of one — so a
    #: concept confined to a single sector is more likely a sector story than a theme.
    min_sectors: int = 1

    def met_by(self, evidence: ThemeEvidence) -> bool:
        return (
            evidence.breadth >= self.min_companies
            and evidence.persistence >= self.min_periods
            and len(evidence.sectors) >= self.min_sectors
        )

    def shortfall(self, evidence: ThemeEvidence) -> str:
        """Why a concept did not clear, phrased so a withdrawal reason can use it verbatim."""
        missing = []
        if evidence.breadth < self.min_companies:
            missing.append(
                f"referenced by {evidence.breadth} companies, needs {self.min_companies}"
            )
        if evidence.persistence < self.min_periods:
            missing.append(
                f"seen in {evidence.persistence} period(s), needs {self.min_periods}"
            )
        if len(evidence.sectors) < self.min_sectors:
            missing.append(
                f"spans {len(evidence.sectors)} sector(s), needs {self.min_sectors}"
            )
        return "; ".join(missing)


def assemble(
    references: list[Reference],
    labels: dict[str, str] | None = None,
    thresholds: Thresholds | None = None,
) -> tuple[list[Theme], list[Theme]]:
    """Group references into themes, and split them on whether they clear the thresholds.

    Returns ``(surfaced, below_threshold)``. The second half is returned rather than discarded
    because it is what a *withdrawal* is decided from: a standing theme whose evidence has
    thinned is not absent from this run, it is present and short — and those are different
    facts. Discarding it would leave withdrawal unable to tell "faded" from "never looked".
    """
    thresholds = thresholds or Thresholds()
    labels = labels or {}

    grouped: dict[str, list[Reference]] = {}
    for reference in references:
        grouped.setdefault(reference.concept, []).append(reference)

    surfaced: list[Theme] = []
    short: list[Theme] = []
    for key, group in grouped.items():
        evidence = ThemeEvidence(references=tuple(group))
        theme = Theme(key=key, label=labels.get(key, key), evidence=evidence)
        (surfaced if thresholds.met_by(evidence) else short).append(theme)

    # Ordered by evidence, then by key, so the same references always produce the same order.
    # Deliberately *not* a ranking: this is a stable presentation order, it carries no meaning
    # about which theme matters more, and nothing downstream may treat it as one.
    surfaced.sort(key=lambda t: (-t.evidence.breadth, -t.evidence.persistence, t.key))
    short.sort(key=lambda t: t.key)
    return surfaced, short

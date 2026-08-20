"""Deciding what counts as a theme.

**Arithmetic, not judgement.** A model asked "what themes are emerging in India" answers
fluently every time, whether or not anything is emerging — the answer is unfalsifiable and
changes between runs. Breadth and persistence are neither: *fourteen companies across three
sectors, referenced in three consecutive quarters* is a claim that can be checked, disagreed
with, and shown to be wrong.

It is also the claim that would have caught the thing this whole change exists for. Transformer
and cable makers were describing data-centre demand in their order-book commentary long before
it reached an index, and no headline reader would have joined those up.

Nothing in this module calls a model, and nothing in it produces a score. Given the same
references it produces the same themes, in the same order, forever.
"""

from __future__ import annotations

import logging
import re
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


# ── concept extraction ────────────────────────────────────────────────────────
#: Concepts the platform recognises, as phrase alternatives. A data file rather than a model
#: call: extraction has to be reproducible for the counts to mean anything, and a model
#: deciding what a paragraph is "about" would give a different answer on a second run.
#:
#: Deliberately a seed list, and deliberately narrow. A concept nobody listed is invisible to
#: detection, which is a real limitation and the honest one to take: the alternative is a model
#: deciding what a paragraph is about, and then the counts stop being reproducible and stop
#: meaning anything. Adding a concept is a data change.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "data_centre": ("data centre", "data center", "hyperscaler", "colocation", "colo facility"),
    "power_transmission": (
        "transmission line",
        "power transmission",
        "substation",
        "transformer",
        "switchgear",
        "grid capacity",
    ),
    "renewables": ("solar", "wind energy", "renewable capacity", "green energy"),
    "green_hydrogen": ("green hydrogen", "electrolyser", "electrolyzer"),
    "defence": ("defence order", "defense order", "indigenisation", "defence capex"),
    "railways": ("railway capex", "vande bharat", "wagon", "locomotive", "rail infrastructure"),
    "electronics_manufacturing": (
        "electronics manufacturing",
        "pli scheme",
        "semiconductor fab",
        "assembly plant",
    ),
    "ev_supply_chain": ("electric vehicle", "battery cell", "charging infrastructure", " ev "),
    "capex_cycle": ("capacity expansion", "capex cycle", "brownfield expansion", "greenfield"),
    "order_book": ("order book", "order inflow", "order intake", "orders received"),
}


def extract(
    symbol: str,
    period: str,
    text: str,
    kind,
    source_ref: str,
    sector: str | None = None,
    period_end=None,
) -> list[Reference]:
    """References to known concepts in one document, one per concept matched.

    One reference per concept per document, however many times the phrase appears. A company
    that says "data centre" forty times in one call is one company saying it once as far as
    breadth is concerned — counting mentions would let a single voluble management team
    manufacture a theme.
    """
    if not text:
        return []

    lowered = f" {text.lower()} "
    found: list[Reference] = []
    for concept, phrases in CONCEPTS.items():
        hit = next((p for p in phrases if p in lowered), None)
        if hit is None:
            continue
        found.append(
            Reference(
                symbol=symbol,
                concept=concept,
                period=period,
                kind=kind,
                source_ref=source_ref,
                sector=sector,
                period_end=period_end,
                excerpt=_excerpt(text, hit),
            )
        )
    return found


def _excerpt(text: str, phrase: str, width: int = 240) -> str:
    """The sentence around a match, so a reader can judge the reference without the document."""
    lowered = text.lower()
    at = lowered.find(phrase)
    if at < 0:
        return ""
    start = max(0, at - width // 2)
    end = min(len(text), at + len(phrase) + width // 2)
    return re.sub(r"\s+", " ", text[start:end]).strip()

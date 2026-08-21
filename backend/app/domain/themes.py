"""What is emerging, and who is positioned to be paid by it.

Two mechanisms live in this file's vocabulary and they fail differently, which is why they are
separate types rather than one blended object:

* a **Theme** is *counted*. Breadth and persistence are arithmetic over documents, so
  "fourteen companies across three sectors, three consecutive quarters" is a claim that can be
  checked and can be wrong. A model asked what is emerging would answer fluently every time,
  whether or not anything was.
* a **ChainLink** is *proposed*. What a data centre consumes is world knowledge, which is the
  kind of answer a model gives reliably — but it is still a proposal, so it carries its
  reasoning and the model that made it, and it can be rejected.

The invariant that keeps the second safe: **a theme may widen attention and may never narrow
it.** Nothing here carries a stance, a conviction or a score, and nothing here can order
instruments. A theme produces names to look at; the strategies still decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class SourceKind(StrEnum):
    """Where a reference to a theme came from, in descending order of signal.

    Ordered deliberately. Commentary and order books are where money is *committed*; news is
    where it is discussed, and by the time a theme is a headline it is priced.
    """

    COMMENTARY = "commentary"
    ORDER_BOOK = "order_book"
    POLICY = "policy"
    FILING = "filing"
    NEWS = "news"


class Exposure(StrEnum):
    """How well a company's connection to a theme is established.

    Three grades and **no numeric strength**, deliberately: a number would be sortable, and
    sorting candidates by theme exposure is a ranking this platform does not permit.
    """

    #: Segment disclosure supports it.
    ESTABLISHED = "established"
    #: Management says so; nothing corroborates it.
    CLAIMED = "claimed"
    #: Neither. Still a displayable answer, and still listed.
    UNESTABLISHED = "unestablished"


@dataclass(frozen=True, slots=True)
class Reference:
    """One company saying one thing in one period, traceable to the document it came from."""

    symbol: str
    #: The concept this reference is about. Themes are groups of references sharing one.
    concept: str
    #: The reporting period this was said in, e.g. `Jun 2026`. Persistence counts these.
    period: str
    kind: SourceKind
    source_ref: str
    excerpt: str = ""
    sector: str | None = None
    period_end: date | None = None


@dataclass(frozen=True, slots=True)
class ThemeEvidence:
    """What a theme is supported by, counted rather than judged."""

    references: tuple[Reference, ...] = ()

    @property
    def companies(self) -> frozenset[str]:
        """Distinct companies that said something.

        Unattributed references are excluded. A policy announcement is not a company saying
        anything, and letting one budget item add to breadth would manufacture the exact "loud
        month" the thresholds exist to reject.
        """
        return frozenset(r.symbol for r in self.references if r.symbol)

    @property
    def sectors(self) -> frozenset[str]:
        return frozenset(r.sector for r in self.references if r.sector)

    @property
    def periods(self) -> tuple[str, ...]:
        """Distinct periods, oldest first, ordered by parsed end where one exists."""
        seen: dict[str, date | None] = {}
        for reference in self.references:
            seen.setdefault(reference.period, reference.period_end)
        return tuple(
            period
            for period, _ in sorted(
                seen.items(), key=lambda kv: (kv[1] is not None, kv[1] or date.min)
            )
        )

    @property
    def breadth(self) -> int:
        """Distinct companies referencing this. One loud company is not a theme."""
        return len(self.companies)

    @property
    def persistence(self) -> int:
        """Distinct periods it has been referenced in. One loud month is not a theme."""
        return len(self.periods)

    @property
    def source_kinds(self) -> frozenset[SourceKind]:
        return frozenset(r.kind for r in self.references)


@dataclass(frozen=True, slots=True)
class Theme:
    """A concept the market is talking about, with what evidences it."""

    key: str
    label: str
    evidence: ThemeEvidence = field(default_factory=ThemeEvidence)
    first_seen: datetime | None = None
    withdrawn_at: datetime | None = None
    withdrawal_reason: str | None = None

    @property
    def is_standing(self) -> bool:
        return self.withdrawn_at is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            # Published, not derived on the client — the counts *are* the claim.
            "breadth": self.evidence.breadth,
            "persistence": self.evidence.persistence,
            "companies": sorted(self.evidence.companies),
            "sectors": sorted(self.evidence.sectors),
            "periods": list(self.evidence.periods),
            "source_kinds": sorted(k.value for k in self.evidence.source_kinds),
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "withdrawn_at": self.withdrawn_at.isoformat() if self.withdrawn_at else None,
            "withdrawal_reason": self.withdrawal_reason,
        }


@dataclass(frozen=True, slots=True)
class ChainLink:
    """One tier of what a theme consumes, and why.

    Stored as an artefact rather than consumed as a transient prompt result. Three properties
    follow from that and all three are requirements: a reader can see *why* a cable maker is on
    their screen, a wrong link can be rejected and stays rejected, and the link is never
    load-bearing — it produces a name to look at, never a measurement.
    """

    theme_key: str
    tier: int
    label: str
    #: What this tier supplies. ``None`` for the first tier, which supplies the theme itself.
    supplies: str | None
    reasoning: str
    #: The model that proposed this. Attribution is what keeps it from reading as a
    #: measurement the platform made.
    proposed_by: str
    #: Supplier categories, in the model's own words. Resolving these to instruments happens
    #: outside the expansion step, against the universe.
    supplier_descriptions: tuple[str, ...] = ()
    rejected: bool = False
    rejected_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "theme_key": self.theme_key,
            "tier": self.tier,
            "label": self.label,
            "supplies": self.supplies,
            "reasoning": self.reasoning,
            "proposed_by": self.proposed_by,
            "supplier_descriptions": list(self.supplier_descriptions),
            "rejected": self.rejected,
            "rejected_reason": self.rejected_reason,
            # Never a platform measurement. Carried so a reader never has to infer it.
            "measured_by_platform": False,
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    """An instrument a chain tier resolved to, and how well its exposure is established."""

    symbol: str
    theme_key: str
    tier: int
    exposure: Exposure
    #: What supports the grade — a segment disclosure, a commentary excerpt, or nothing.
    exposure_basis: str | None = None
    matched_description: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "theme_key": self.theme_key,
            "tier": self.tier,
            "exposure": self.exposure.value,
            "exposure_basis": self.exposure_basis,
            "matched_description": self.matched_description,
        }


@dataclass(frozen=True, slots=True)
class UnresolvedTier:
    """A tier that produced no Indian listed candidate, and why.

    A real answer rather than a gap. A tier like EUV lithography has no Indian expression at
    all, and an engine that felt obliged to return something would hand over a marginal
    smallcap whose business description happened to match.
    """

    theme_key: str
    tier: int
    label: str
    reason: str
    unresolved_descriptions: tuple[str, ...] = ()

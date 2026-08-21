"""One pass: read what is available, count it, expand it, resolve it, record it.

The piece that makes the rest usable. Everything it orchestrates already exists and is tested
in isolation; what this adds is the order they run in and — more importantly — what happens
when a step cannot run at all.

**Degradation is the design, not an error path.** Commentary is scrape-only and fails often;
a model may be unreachable; the universe may have fallen back to a bundled list. A run must
survive every one of those and *say which happened*, because a run that surfaced three themes
because its documents would not download must never be mistaken for a market that went quiet.

Two rules carried in from earlier changes, both of which prevent silent damage:

* **A run that read nothing withdraws nothing.** Absence is not evidence.
* **A rejected link stays rejected.** Re-proposing it every run is how a review surface becomes
  one people stop reading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.data.protocols import UniverseSnapshot
from app.domain.themes import Reference, SourceKind
from app.themes import resolve
from app.themes.detect import Thresholds, assemble
from app.themes.sources import SourceResult
from app.themes.store import ThemeStore

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Gathered:
    """What the source pass produced, and what it could not read."""

    references: list[Reference] = field(default_factory=list)
    documents_read: int = 0
    unavailable: tuple[SourceKind, ...] = ()

    @property
    def read_nothing(self) -> bool:
        """No reference from any source. Distinct from "read plenty and found nothing"."""
        return not self.references and self.documents_read == 0


@dataclass(frozen=True, slots=True)
class ThemeRunResult:
    run_id: int
    outcome: str
    surfaced: int = 0
    refreshed: int = 0
    withdrawn: int = 0
    chains_expanded: int = 0
    candidates: int = 0
    tiers_without_indian_exposure: int = 0
    documents_read: int = 0
    sources_unavailable: tuple[str, ...] = ()
    reason: str | None = None
    #: Distinct businesses the run broke coarse tiers into.
    sub_categories: int = 0
    #: Sub-categories description matching left empty, that a search was attempted for.
    searched: int = 0
    #: Names search proposed that the universe confirmed, and names it refused. Reported
    #: separately because the refusals are the safety property, not an error rate.
    proposals_confirmed: int = 0
    proposals_refused: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "outcome": self.outcome,
            "surfaced": self.surfaced,
            "refreshed": self.refreshed,
            "withdrawn": self.withdrawn,
            "chains_expanded": self.chains_expanded,
            "candidates": self.candidates,
            "tiers_without_indian_exposure": self.tiers_without_indian_exposure,
            "documents_read": self.documents_read,
            "sources_unavailable": list(self.sources_unavailable),
            "reason": self.reason,
            "sub_categories": self.sub_categories,
            "searched": self.searched,
            "proposals_confirmed": self.proposals_confirmed,
            "proposals_refused": self.proposals_refused,
        }


def compose_gatherer(
    commentary: SourceResult | None = None,
    policy: SourceResult | None = None,
    filings: SourceResult | None = None,
):
    """Build a gatherer from already-read sources.

    Kept separate from the adapters so a run can be assembled from whichever answered. The
    unavailable list is what a run reports, and it is derived from the adapters themselves
    rather than inferred from a thin result.
    """
    from app.domain.themes import SourceKind as _Kind

    def gather() -> Gathered:
        references = []
        documents = 0
        unavailable = []

        for result, kind in (
            (commentary, _Kind.COMMENTARY),
            (policy, _Kind.POLICY),
            (filings, _Kind.FILING),
        ):
            if result is None:
                continue
            references.extend(result.references)
            documents += result.documents_read
            if not result.available:
                unavailable.append(kind)

        return Gathered(
            references=references,
            documents_read=documents,
            unavailable=tuple(unavailable),
        )

    return gather


class ThemeRunner:
    """Drives one theme run from sources to stored candidates."""

    def __init__(
        self,
        store: ThemeStore,
        gatherer,
        universe_source,
        expander=None,
        profile_source=None,
        thresholds: Thresholds | None = None,
        labels: dict[str, str] | None = None,
        matcher=None,
        researcher=None,
    ) -> None:
        self._store = store
        self._gather = gatherer
        self._universe_source = universe_source
        self._expander = expander
        #: Business descriptions. Without them resolution has nothing to match against and
        #: says so, rather than falling back to company names — which is the defect this
        #: seam exists to have replaced.
        self._profiles = profile_source
        self._thresholds = thresholds or Thresholds()
        self._labels = labels or {}
        #: The precision half of resolution. Absent, a tier keeps everything word overlap
        #: shortlisted and says plainly that nothing read it.
        self._matcher = matcher
        #: Decomposition and participant search. Absent, tiers resolve coarsely and no
        #: search is ever attempted — which is what a platform with no search key does.
        self._researcher = researcher

    def run(self, trigger: str = "requested") -> ThemeRunResult:
        already = self._store.running_run()
        if already is not None:
            # Refused rather than queued. Two runs writing the same themes would interleave
            # their counts, and a count that is a blend of two passes is not a measurement.
            return ThemeRunResult(
                run_id=already,
                outcome="refused",
                reason=f"run {already} is already in progress",
            )

        run_id = self._store.start_run(trigger)

        try:
            gathered = self._gather()
        except Exception as exc:
            log.warning("theme source gathering failed: %s", exc)
            self._store.finish_run(run_id, "failed", reason=str(exc))
            return ThemeRunResult(run_id=run_id, outcome="failed", reason=str(exc))

        unavailable = tuple(k.value for k in gathered.unavailable)

        if gathered.read_nothing:
            # Nothing was read, so nothing is known. Emphatically not "no themes found" —
            # and above all, nothing is withdrawn.
            self._store.finish_run(
                run_id,
                "no_reading",
                sources_unavailable=unavailable,
                reason="no source could be read; no theme was assessed",
            )
            return ThemeRunResult(
                run_id=run_id,
                outcome="no_reading",
                sources_unavailable=unavailable,
                reason="no source could be read; no theme was assessed",
            )

        surfaced_themes, short_themes = assemble(
            gathered.references, labels=self._labels, thresholds=self._thresholds
        )

        new, refreshed = self._store.record(surfaced_themes)
        withdrawn = self._store.withdraw_short(short_themes, self._thresholds.shortfall)

        universe = self._universe_source.snapshot()
        outcome = self._expand_and_resolve(surfaced_themes, universe)

        self._store.finish_run(
            run_id,
            "complete",
            sources_unavailable=unavailable,
            documents_read=gathered.documents_read,
        )
        return ThemeRunResult(
            run_id=run_id,
            outcome="complete",
            surfaced=new,
            refreshed=refreshed,
            withdrawn=withdrawn,
            documents_read=gathered.documents_read,
            sources_unavailable=unavailable,
            **outcome,
        )

    def _expand_and_resolve(self, themes, universe: UniverseSnapshot) -> dict[str, int]:
        """Expand each theme's chain, resolve it, then research it. Never fatal."""
        totals = {
            "chains_expanded": 0,
            "candidates": 0,
            "tiers_without_indian_exposure": 0,
            "sub_categories": 0,
            "searched": 0,
            "proposals_confirmed": 0,
            "proposals_refused": 0,
        }
        if self._expander is None:
            return totals

        profiles = self._profiles.all() if self._profiles is not None else None

        for theme in themes:
            try:
                tiers = self._expander(theme.label or theme.key)
            except Exception as exc:
                # One theme failing to expand must not end the run. The theme itself is
                # already recorded and is useful without a chain.
                log.warning("chain expansion failed for %s: %s", theme.key, exc)
                continue
            if not tiers:
                continue

            self._store.record_chain(theme.key, tiers)
            totals["chains_expanded"] += 1

            # Read back rather than resolving what was just proposed: the stored chain is the
            # one carrying rejections, and resolving the proposal would quietly reinstate a
            # link the reader had already thrown out.
            stored = self._store.chain(theme.key)
            references = list(theme.evidence.references)
            found, unresolved = resolve.resolve_chain(
                theme.key,
                stored,
                universe,
                references=references,
                profiles=profiles,
                matcher=self._matcher,
            )
            totals["candidates"] += self._store.record_candidates(found)
            totals["tiers_without_indian_exposure"] += len(unresolved)

            totals_from_research = self._research(
                theme.key, stored, universe, references, {c.symbol for c in found}
            )
            for key, value in totals_from_research.items():
                totals[key] += value

        return totals

    def _research(
        self,
        theme_key: str,
        tiers: list[dict[str, Any]],
        universe: UniverseSnapshot,
        references: list[Reference],
        already: set[str],
    ) -> dict[str, int]:
        """Decompose and search one chain. Adds candidates; never removes one.

        Failure here costs the extra candidates and nothing else — the coarse resolution above
        is already recorded, so a decomposition model that is down degrades a run rather than
        failing it.
        """
        empty = {
            "candidates": 0,
            "tiers_without_indian_exposure": 0,
            "sub_categories": 0,
            "searched": 0,
            "proposals_confirmed": 0,
            "proposals_refused": 0,
            "chains_expanded": 0,
        }
        if self._researcher is None:
            return empty

        try:
            research = self._researcher.research(
                theme_key, tiers, universe, references=references, already=already
            )
        except Exception as exc:
            log.warning("tier research failed for %s: %s", theme_key, exc)
            return empty

        confirmed = sum(1 for p in research.proposals if p.is_candidate)
        return {
            **empty,
            "candidates": self._store.record_candidates(research.candidates),
            "tiers_without_indian_exposure": len(research.unresolved),
            "sub_categories": research.sub_categories,
            "searched": research.searched,
            "proposals_confirmed": confirmed,
            "proposals_refused": len(research.proposals) - confirmed,
        }

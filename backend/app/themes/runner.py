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
        chains, candidates, gaps = self._expand_and_resolve(surfaced_themes, universe)

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
            chains_expanded=chains,
            candidates=candidates,
            tiers_without_indian_exposure=gaps,
            documents_read=gathered.documents_read,
            sources_unavailable=unavailable,
        )

    def _expand_and_resolve(self, themes, universe: UniverseSnapshot) -> tuple[int, int, int]:
        """Expand each theme's chain and resolve it to candidates. Never fatal."""
        if self._expander is None:
            return 0, 0, 0

        chains = candidates = gaps = 0
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
            chains += 1

            # Read back rather than resolving what was just proposed: the stored chain is the
            # one carrying rejections, and resolving the proposal would quietly reinstate a
            # link the reader had already thrown out.
            stored = self._store.chain(theme.key)
            found, unresolved = resolve.resolve_chain(
                theme.key,
                stored,
                universe,
                references=list(theme.evidence.references),
                profiles=self._profiles.all() if self._profiles is not None else None,
            )
            candidates += self._store.record_candidates(found)
            gaps += len(unresolved)

        return chains, candidates, gaps

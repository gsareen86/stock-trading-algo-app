"""Decompose every tier, resolve what comes out, and search only what stays empty.

The order matters and it is the whole design.

**Coarse resolution runs first and its candidates are never touched.** Research may only widen.
A tier that matched three companies on their business descriptions still has those three
afterwards, whatever decomposition and search do — nothing here removes a candidate, gates one,
or reorders anything.

**Then every tier is decomposed**, not only the empty ones. That is the change from how this
was first designed. As a fallback it would fire when a tier resolved to nothing, which made
sense when resolution matched company names and found three of nineteen defence constituents.
Matching on business descriptions fixed that, and left a different problem: a coarse tier is
imprecise in *both* directions. It returns weak matches for companies that barely qualify and
misses the one that describes itself precisely.

**Search runs last, and only where description matching produced nothing.** It is the narrow,
risky half — the one place a model proposes a name rather than a category — so it runs against
the smallest possible surface, and everything it proposes goes through
`propose.validate` before it can become anything.

**Measured, on the fixture.** Against thirty real business descriptions, an OSAT sub-category
matches CG Power on four words and ranks it first, where the coarse tier tied it with Infosys,
Shree Cement and Voltas on one. Kaynes is invisible to both, at any granularity, because its
published description says "integrated electronics manufacturer" and its assembly plant post-
dates it — that one is reachable only by search. Neither half subsumes the other.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.data.protocols import UniverseSnapshot
from app.domain.themes import Candidate, Reference, UnresolvedTier
from app.themes import resolve
from app.themes.propose import Proposal, ValidatedProposal, to_candidates, validate

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TierResearch:
    """What researching one chain produced, beyond what coarse resolution already had."""

    sub_categories: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    unresolved: list[UnresolvedTier] = field(default_factory=list)
    searched: int = 0
    proposals: list[ValidatedProposal] = field(default_factory=list)
    #: Tiers a model could not decompose. They still resolved by their coarse description.
    undecomposed: tuple[str, ...] = ()

    @property
    def offered(self) -> int:
        return len(self.candidates)


def search_query(sub_category: str, tier_label: str = "") -> str:
    """What to ask the web for participants in a sub-category.

    Names the exchanges rather than the country. "Indian companies" returns market commentary
    and listicles; "NSE BSE listed" returns pages that are actually about listed equities,
    which is the population the answer has to come from.
    """
    subject = " ".join((sub_category or "").split())
    context = " ".join((tier_label or "").split())
    parts = [subject]
    if context and context.lower() not in subject.lower():
        parts.append(context)
    parts.append("India NSE BSE listed companies")
    return " ".join(parts)[:380]


class TierResearcher:
    """Runs decomposition, sub-category resolution and participant search over a chain.

    Every collaborator is optional and absent means *that step did not run*, never that it ran
    and found nothing. A platform with no search key still decomposes; one with no model still
    resolves coarsely. Each missing piece costs exactly its own capability.
    """

    def __init__(
        self,
        store,
        decomposer=None,
        searcher=None,
        proposer=None,
        profiles=None,
        matcher=None,
    ) -> None:
        self._store = store
        self._decompose = decomposer
        self._search = searcher
        self._propose = proposer
        self._profiles = profiles
        self._matcher = matcher

    def research(
        self,
        theme_key: str,
        tiers: list[dict[str, Any]],
        universe: UniverseSnapshot,
        references: list[Reference] | None = None,
        already: set[str] | None = None,
    ) -> TierResearch:
        """Decompose, resolve and search one theme's chain.

        ``already`` is the symbols coarse resolution has offered. Passed in so research does
        not re-offer them under a sub-category — the same company arriving twice for one tier
        reads as two findings.
        """
        if self._decompose is None:
            return TierResearch()

        held = set(already or ())
        found: list[Candidate] = []
        gaps: list[UnresolvedTier] = []
        proposals: list[ValidatedProposal] = []
        undecomposed: list[str] = []
        written = searched = 0

        for tier in tiers:
            if tier.get("rejected"):
                # A rejected link contributes nothing, and decomposing it would reinstate it
                # under six new names.
                continue

            number = int(tier.get("tier", 1))
            label = str(tier.get("label") or "").strip()
            reasoning = str(tier.get("reasoning") or "")
            coarse = list(tier.get("supplier_descriptions") or [])

            try:
                subs = self._decompose(label, reasoning, coarse) or []
            except Exception as exc:
                # One tier failing to decompose must not end the run. The tier is already
                # resolved coarsely and is useful without a breakdown.
                log.warning("decomposition failed for %s tier %s: %s", theme_key, label, exc)
                undecomposed.append(label)
                continue

            if not subs:
                undecomposed.append(label)
                continue

            written += self._store.record_sub_categories(theme_key, number, label, subs)
            stored = {
                row["label"]: row
                for row in self._store.sub_categories(theme_key)
                if row["tier"] == number
            }

            for sub in subs:
                sub_label = str(sub.get("label") or "").strip()
                row = stored.get(sub_label)
                candidates, missing = resolve.resolve_tier(
                    theme_key=theme_key,
                    tier=number,
                    label=sub_label,
                    supplier_descriptions=list(sub.get("supplier_descriptions") or []),
                    universe=universe,
                    # Deliberately no `references`: commentary evidence belongs to the theme's
                    # own tier, and re-offering it under every sub-category would multiply one
                    # company's single statement into six candidates.
                    references=None,
                    notable_examples=[
                        e for e in (sub.get("notable_examples") or []) if isinstance(e, dict)
                    ],
                    profiles=self._profiles,
                    matcher=self._matcher,
                    reasoning=str(sub.get("reasoning") or ""),
                )

                fresh = [c for c in candidates if c.symbol not in held]
                for candidate in fresh:
                    held.add(candidate.symbol)
                found.extend(fresh)

                if candidates:
                    # Description matching answered. Searching anyway would spend an
                    # allowance on a question already answered.
                    continue

                if missing is not None:
                    gaps.append(missing)

                searched_this, proposed = self._search_sub_category(
                    theme_key=theme_key,
                    tier=number,
                    sub_label=sub_label,
                    tier_label=label,
                    reasoning=str(sub.get("reasoning") or ""),
                    universe=universe,
                    row=row,
                )
                searched += int(searched_this)
                proposals.extend(proposed)

                for candidate in to_candidates(proposed, theme_key, number, references):
                    if candidate.symbol in held:
                        continue
                    held.add(candidate.symbol)
                    found.append(candidate)

        return TierResearch(
            sub_categories=written,
            candidates=found,
            unresolved=gaps,
            searched=searched,
            proposals=proposals,
            undecomposed=tuple(undecomposed),
        )

    def _search_sub_category(
        self,
        theme_key: str,
        tier: int,
        sub_label: str,
        tier_label: str,
        reasoning: str,
        universe: UniverseSnapshot,
        row: dict[str, Any] | None,
    ) -> tuple[bool, list[ValidatedProposal]]:
        """Search one empty sub-category and validate whatever it proposes.

        Returns ``(the search ran, validated proposals)``. Every outcome is recorded against
        the sub-category, including the ones that produced nothing, because a reader deciding
        whether an empty tier is real needs to know whether anybody looked.
        """
        if self._search is None or self._propose is None:
            return False, []

        try:
            results = self._search(search_query(sub_label, tier_label))
        except Exception as exc:
            log.warning("search failed for %r: %s", sub_label, exc)
            if row:
                self._store.mark_searched(row["id"], "unavailable")
            return False, []

        payload = results.as_dict() if hasattr(results, "as_dict") else dict(results)
        outcome = str(payload.get("outcome") or "unavailable")
        if row:
            self._store.mark_searched(row["id"], outcome)

        if not payload.get("available"):
            # Unconfigured, exhausted or unreachable. Recorded as itself and never as an
            # empty result, which would read as "the web says nothing".
            log.info("sub-category %r not searched: %s", sub_label, payload.get("reason"))
            return False, []

        hits = payload.get("hits") or []
        if not hits:
            return True, []

        try:
            proposed = self._propose(sub_label, reasoning, hits) or []
        except Exception as exc:
            log.warning("participant proposal failed for %r: %s", sub_label, exc)
            return True, []

        candidates = [
            Proposal(
                company=str(entry.get("company") or "").strip(),
                sub_category=sub_label,
                rationale=str(entry.get("rationale") or ""),
                sources=tuple(entry.get("sources") or ()),
                proposed_by=str(entry.get("proposed_by") or ""),
            )
            for entry in proposed
            if str(entry.get("company") or "").strip()
        ]
        if not candidates:
            return True, []

        validated = validate(candidates, universe)
        # Written whatever they resolved to. The refusals are the record that the platform
        # declined to act on a name, and they only exist if they are stored.
        self._store.record_proposals(theme_key, tier, validated)
        return True, validated

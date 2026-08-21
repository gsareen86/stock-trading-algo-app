"""Turning a proposed name into a symbol, or into nothing.

**This module is the reason the research agent is safe to have.** Everywhere else in the theme
engine a model proposes a *category*, which cannot be bought, and resolution against the
platform's own universe is what produces a name. Participant search breaks that: the model
proposes a name directly. This is the step that puts the platform back in charge of it.

A proposal is inert until this file confirms it. It may become a candidate only by matching an
instrument the platform already holds, which makes three whole classes of failure structurally
impossible rather than merely unlikely: a company that does not exist, a company listed
somewhere other than India, and a company that is real and private.

**Ambiguity produces nothing, and Indian markets make that rule earn its keep.** Bharat
Electronics and Bharat Dynamics are different companies with different businesses. Several Tata
entities are separately listed. A name matching more than one instrument is not a near miss to
be broken by ranking, alphabet or market capitalisation -- it is a question the platform cannot
answer, and answering it anyway would put a name in front of a reader that nothing chose.

**The grade records where it came from.** A search-derived candidate is `unestablished` and its
basis says so, naming the source. Search corroborates nothing by itself: it is a page that
mentioned a company. Only the company's own commentary can raise the grade, and then the basis
cites the commentary rather than the search.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from app.data.protocols import UniverseSnapshot
from app.domain.themes import Candidate, Exposure, Reference

log = logging.getLogger(__name__)

#: Corporate furniture. Stripped so "Kaynes Technology India Limited" and "Kaynes Technology"
#: are the same company, which they are.
_SUFFIXES = (
    "limited", "ltd", "private", "pvt", "corporation", "corp", "company", "co",
    "incorporated", "inc", "plc", "holdings", "group", "enterprises",
)

#: Words too common in Indian listed names to identify anything on their own. A proposal that
#: reduces to one of these is not a company name, it is a family.
_NOT_IDENTIFYING = frozenset(
    {"bharat", "tata", "aditya", "birla", "mahindra", "reliance", "adani", "jsw", "hindustan",
     "indian", "india", "national", "state", "shree", "sri", "new", "the"}
)

_PUNCT = re.compile(r"[^a-z0-9 ]+")


class ProposalOutcome(StrEnum):
    """What the universe said about a proposed name."""

    #: Matched exactly one instrument. The only outcome that can become a candidate.
    RESOLVED = "resolved"
    #: Matched nothing. Recorded, never offered — it may be foreign, unlisted or invented.
    NOT_FOUND = "not_found"
    #: Matched more than one. Deliberately produces nothing.
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class Proposal:
    """A company name a model read on a page, with what supports it."""

    company: str
    sub_category: str
    rationale: str = ""
    sources: tuple[str, ...] = ()
    proposed_by: str = ""

    @property
    def is_cited(self) -> bool:
        return bool(self.sources)


@dataclass(frozen=True, slots=True)
class ValidatedProposal:
    """A proposal after the universe has had its say."""

    proposal: Proposal
    outcome: ProposalOutcome
    symbol: str | None = None
    matched_name: str | None = None
    #: Every instrument an ambiguous name touched, so a reader can see what the confusion was.
    matched: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def is_candidate(self) -> bool:
        return self.outcome is ProposalOutcome.RESOLVED and self.symbol is not None

    def as_dict(self) -> dict:
        return {
            "company": self.proposal.company,
            "sub_category": self.proposal.sub_category,
            "rationale": self.proposal.rationale,
            "sources": list(self.proposal.sources),
            "proposed_by": self.proposal.proposed_by,
            "outcome": self.outcome.value,
            "symbol": self.symbol,
            "matched_name": self.matched_name,
            "matched": list(self.matched),
            "reason": self.reason,
        }


def normalise(name: str) -> str:
    """A company name reduced to the words that identify it."""
    cleaned = _PUNCT.sub(" ", (name or "").lower())
    words = [w for w in cleaned.split() if w and w not in _SUFFIXES]
    return " ".join(words)


def identifying(name: str) -> bool:
    """Whether a normalised name says which company, rather than which family.

    "Tata" is not a company. Treating it as one would resolve it by whichever Tata entity
    happened to sort first, which is a name nobody chose reaching a reader as though
    something had.
    """
    words = normalise(name).split()
    if not words:
        return False
    return not all(word in _NOT_IDENTIFYING for word in words)


def validate(proposals: list[Proposal], universe: UniverseSnapshot) -> list[ValidatedProposal]:
    """Resolve each proposed name against the universe. Never guesses.

    Three passes, narrowing: exact on the normalised name, then containment either way, then
    nothing. Each pass requires a *unique* hit — a pass matching two instruments stops rather
    than falling through to a looser one, because a looser rule cannot resolve an ambiguity a
    stricter one already found.
    """
    index: dict[str, list[tuple[str, str]]] = {}
    for instrument in universe.instruments:
        key = normalise(instrument.name or instrument.symbol)
        if key:
            index.setdefault(key, []).append((instrument.symbol, instrument.name or ""))

    results: list[ValidatedProposal] = []

    for proposal in proposals:
        if not proposal.is_cited:
            # Should not reach here — the tool discards these — so it is worth saying loudly
            # rather than dropping quietly.
            log.warning("uncited proposal reached validation: %r", proposal.company)
            results.append(
                ValidatedProposal(
                    proposal=proposal,
                    outcome=ProposalOutcome.NOT_FOUND,
                    reason="no source; a proposal without one is not offered",
                )
            )
            continue

        wanted = normalise(proposal.company)
        if not wanted:
            results.append(
                ValidatedProposal(
                    proposal=proposal,
                    outcome=ProposalOutcome.NOT_FOUND,
                    reason="not a usable company name",
                )
            )
            continue

        if not identifying(proposal.company):
            results.append(
                ValidatedProposal(
                    proposal=proposal,
                    outcome=ProposalOutcome.AMBIGUOUS,
                    reason=f"{proposal.company!r} names a group, not a company",
                )
            )
            continue

        exact = index.get(wanted, [])
        if len(exact) == 1:
            symbol, name = exact[0]
            results.append(
                ValidatedProposal(
                    proposal=proposal,
                    outcome=ProposalOutcome.RESOLVED,
                    symbol=symbol,
                    matched_name=name,
                    matched=(symbol,),
                )
            )
            continue
        if len(exact) > 1:
            results.append(_ambiguous(proposal, exact))
            continue

        # Containment either way: "Kaynes Technology" against "Kaynes Technology India", and
        # a proposal carrying extra words against a shorter listed name.
        touched = [
            (symbol, name)
            for key, entries in index.items()
            for symbol, name in entries
            if key.startswith(wanted) or wanted.startswith(key)
        ]
        unique = {symbol: name for symbol, name in touched}
        if len(unique) == 1:
            symbol, name = next(iter(unique.items()))
            results.append(
                ValidatedProposal(
                    proposal=proposal,
                    outcome=ProposalOutcome.RESOLVED,
                    symbol=symbol,
                    matched_name=name,
                    matched=(symbol,),
                )
            )
        elif len(unique) > 1:
            results.append(_ambiguous(proposal, list(unique.items())))
        else:
            results.append(
                ValidatedProposal(
                    proposal=proposal,
                    outcome=ProposalOutcome.NOT_FOUND,
                    reason=(
                        f"{proposal.company!r} matched no instrument in the universe; it may "
                        "be listed elsewhere, unlisted, or not exist"
                    ),
                )
            )

    return results


def _ambiguous(proposal: Proposal, matches: list[tuple[str, str]]) -> ValidatedProposal:
    symbols = tuple(sorted(symbol for symbol, _ in matches))
    return ValidatedProposal(
        proposal=proposal,
        outcome=ProposalOutcome.AMBIGUOUS,
        matched=symbols,
        reason=(
            f"{proposal.company!r} matched {len(symbols)} instruments "
            f"({', '.join(symbols)}); the platform will not pick one"
        ),
    )


def to_candidates(
    validated: list[ValidatedProposal],
    theme_key: str,
    tier: int,
    references: list[Reference] | None = None,
) -> list[Candidate]:
    """Candidates from the proposals the universe confirmed, and only those.

    Graded `unestablished` on the strength of search alone, always. A page mentioning a
    company is not the company saying anything, and the grade has to mean the same thing here
    as it does everywhere else or it stops being usable.

    A company whose *own* commentary discusses the theme is a different matter: it has said so
    itself, which is what `claimed` means. Then the basis cites the commentary — the thing that
    actually establishes it — and search is recorded as how the name was found rather than as
    what supports it.
    """
    spoke: dict[str, Reference] = {}
    for reference in references or []:
        if reference.symbol:
            spoke.setdefault(reference.symbol, reference)

    candidates: list[Candidate] = []
    seen: set[str] = set()

    for row in validated:
        if not row.is_candidate or row.symbol in seen:
            continue
        seen.add(row.symbol)

        source = row.proposal.sources[0] if row.proposal.sources else "search"
        corroboration = spoke.get(row.symbol)

        if corroboration is not None:
            exposure = Exposure.CLAIMED
            basis = (
                f"discussed the theme in {corroboration.period} "
                f"({corroboration.kind.value}); found by search of {source}"
            )
        else:
            exposure = Exposure.UNESTABLISHED
            basis = (
                f"proposed by search and confirmed against the universe, not corroborated "
                f"by anything the platform measured: {source}"
            )

        candidates.append(
            Candidate(
                symbol=row.symbol,
                theme_key=theme_key,
                tier=tier,
                exposure=exposure,
                exposure_basis=basis,
                matched_description=f"search: {row.proposal.sub_category}",
            )
        )

    return sorted(candidates, key=lambda c: c.symbol)

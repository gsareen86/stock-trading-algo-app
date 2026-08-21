"""Turning a chain into names that can actually be bought.

**This is where the boundary sits.** Evidence may come from anywhere and a chain may describe
activity anywhere — the theme this engine exists for originated in American hyperscaler capex,
and an India-only detector would very likely never have surfaced it. Only *candidates* are
constrained: every name offered is an instrument in the platform's own NSE universe.

A tier with no Indian instrument is a real answer and is reported as one. Its recognisable
foreign names travel with it as explanation, marked not investable, because a chain with a hole
in it reads as a chain nobody understood — and knowing that a tier's value accrues to companies
you cannot buy here is worth knowing.

**Two ways a company reaches a tier, and they are not equally strong.** A company that
*discussed* the theme in its own commentary has said so itself; a company matched because its
industry looks right has said nothing. Both are offered, both carry which of the two they are,
and nothing here converts one into the other.
"""

from __future__ import annotations

import logging
import re

from app.data.protocols import UniverseSnapshot
from app.domain.themes import Candidate, Exposure, Reference, UnresolvedTier

log = logging.getLogger(__name__)

#: Words that carry no discriminating power in a supplier description. Matching on these would
#: pair "transformer manufacturers" with every manufacturer in the index.
STOPWORDS = frozenset(
    {
        "and", "or", "of", "the", "a", "an", "for", "with", "to", "in",
        "company", "companies", "firm", "firms", "manufacturer", "manufacturers",
        "manufacturing", "provider", "providers", "supplier", "suppliers", "producer",
        "producers", "operator", "operators", "vendor", "vendors", "maker", "makers",
        "services", "service", "systems", "system", "solutions", "solution",
        "equipment", "products", "product", "industry", "industries", "sector",
        "large", "scale", "specialized", "specialised", "high", "grade",
    }
)

#: A description must contribute at least one word this long to match on. Short tokens produce
#: accidental matches — "it", "ev", "gas" inside unrelated names.
MIN_TERM_LENGTH = 4

#: Above this, a description has not narrowed to anything a reader can act on, and is reported
#: as too broad rather than sliced arbitrarily.
MAX_PER_DESCRIPTION = 8


def terms(description: str) -> list[str]:
    """The discriminating words in a supplier description."""
    words = re.findall(r"[a-z]+", (description or "").lower())
    return [w for w in words if len(w) >= MIN_TERM_LENGTH and w not in STOPWORDS]


def _haystack(instrument) -> str:
    return f"{instrument.name or ''} {instrument.sector or ''} {instrument.symbol}".lower()


def match_description(
    description: str, universe: UniverseSnapshot
) -> tuple[list[tuple[str, str]], str | None]:
    """Instruments matching a supplier description, on its most discriminating term.

    Returns ``(matches, too_broad_reason)``.

    **The rarest term wins, and that is the whole design.** "Transformer manufacturers" yields
    `transformer`, `manufacturers` — the first matches one company in the NIFTY 500, the second
    is a stopword. "Power distribution and switchgear providers" yields `switchgear` (nothing),
    `distribution`, and `power` (twenty-one names). Taking the first match in universe order
    gave the alphabetically-earliest power companies for a description about switchgear, which
    is not a coarse answer — it is a wrong one wearing the shape of research.

    A description whose best term still matches more names than a reader can act on is reported
    as **too broad** rather than sliced. An arbitrary eight of twenty-one is worse than an
    honest "this did not narrow to anything".
    """
    wanted = terms(description)
    if not wanted:
        return [], "no discriminating terms"

    by_term: dict[str, list[str]] = {}
    for instrument in universe.instruments:
        haystack = _haystack(instrument)
        for term in wanted:
            if term in haystack:
                by_term.setdefault(term, []).append(instrument.symbol)

    if not by_term:
        return [], None

    # Fewest matches first: the rarest term is the one carrying the meaning.
    term, symbols = min(by_term.items(), key=lambda kv: (len(kv[1]), kv[0]))
    if len(symbols) > MAX_PER_DESCRIPTION:
        return [], (
            f"'{term}' matches {len(symbols)} companies — too broad to narrow this tier"
        )

    return [(symbol, term) for symbol in symbols], None


def resolve_tier(
    theme_key: str,
    tier: int,
    label: str,
    supplier_descriptions: list[str],
    universe: UniverseSnapshot,
    references: list[Reference] | None = None,
    notable_examples: list[dict] | None = None,
) -> tuple[list[Candidate], UnresolvedTier | None]:
    """Candidates for one tier, or a statement that it has no Indian listed expression."""
    listed = {i.symbol for i in universe.instruments}
    candidates: dict[str, Candidate] = {}

    # Path one, and the stronger of the two: companies that discussed the theme themselves.
    # These are only offered where the tier is the theme's own — a company talking about data
    # centres is evidence about data centres, not about transformers.
    if tier == 1:
        for reference in references or []:
            if reference.symbol not in listed or reference.symbol in candidates:
                continue
            candidates[reference.symbol] = Candidate(
                symbol=reference.symbol,
                theme_key=theme_key,
                tier=tier,
                exposure=Exposure.CLAIMED,
                exposure_basis=(
                    f"discussed the theme in {reference.period} "
                    f"({reference.kind.value})"
                ),
                matched_description="own commentary",
            )

    # Path two: the industry looks right. Nobody has said anything.
    unresolved: list[str] = []
    for description in supplier_descriptions or []:
        matches, too_broad = match_description(description, universe)
        if not matches:
            # Recorded either way, and a too-broad description records why — "nothing matched"
            # and "everything matched" are different problems and want different fixes.
            unresolved.append(f"{description} ({too_broad})" if too_broad else description)
            continue
        for symbol, term in matches:
            if symbol in candidates:
                continue
            candidates[symbol] = Candidate(
                symbol=symbol,
                theme_key=theme_key,
                tier=tier,
                exposure=Exposure.UNESTABLISHED,
                exposure_basis=f"industry or name matches '{term}'; nothing corroborates it",
                matched_description=description,
            )

    if candidates:
        return sorted(candidates.values(), key=lambda c: c.symbol), None

    # Nothing matched — and the wording of that matters more than it looks.
    #
    # This says what the platform actually knows: no company's *name or NSE industry* matched.
    # It is emphatically not "no Indian company does this". Kaynes Technology and CG Power are
    # both building semiconductor assembly plants and neither carries a semiconductor word in
    # its name or its "Capital Goods" classification, so a tier for OSAT resolves to nothing
    # here while two real candidates sit in the universe unmatched.
    #
    # Claiming the market has no exposure, on evidence this shallow, would be the engine's
    # most confidently wrong output. `theme-research-agent` is the change that goes looking
    # properly; until then this states its own limits.
    examples = ", ".join(
        e["name"] for e in (notable_examples or []) if isinstance(e, dict) and e.get("name")
    )
    reason = (
        "no company matched on name or industry — this tier may still have Indian exposure "
        "that name matching cannot see"
    )
    if examples:
        reason += f"; known suppliers include {examples}, not listed in India"

    return [], UnresolvedTier(
        theme_key=theme_key,
        tier=tier,
        label=label,
        reason=reason,
        unresolved_descriptions=tuple(unresolved or supplier_descriptions or ()),
    )


def resolve_chain(
    theme_key: str,
    tiers: list[dict],
    universe: UniverseSnapshot,
    references: list[Reference] | None = None,
) -> tuple[list[Candidate], list[UnresolvedTier]]:
    """Every tier of a chain, skipping links a reader has rejected.

    A rejected link contributes nothing and is not silently reinstated — that is what makes
    rejecting one worth the reader's time.
    """
    candidates: list[Candidate] = []
    unresolved: list[UnresolvedTier] = []

    for tier in tiers:
        if tier.get("rejected"):
            continue
        found, missing = resolve_tier(
            theme_key=theme_key,
            tier=int(tier.get("tier", 1)),
            label=str(tier.get("label") or ""),
            supplier_descriptions=list(tier.get("supplier_descriptions") or []),
            universe=universe,
            references=references,
            notable_examples=list(tier.get("notable_examples") or []),
        )
        candidates.extend(found)
        if missing is not None:
            unresolved.append(missing)

    return candidates, unresolved

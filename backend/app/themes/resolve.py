"""Turning a chain into names that can actually be bought.

**This is where the boundary sits.** Evidence may come from anywhere and a chain may describe
activity anywhere — the theme this engine exists for originated in American hyperscaler capex,
and an India-only detector would very likely never have surfaced it. Only *candidates* are
constrained: every name offered is an instrument in the platform's own NSE universe.

A tier with no Indian instrument is a real answer and is reported as one. Its recognisable
foreign names travel with it as explanation, marked not investable, because a chain with a hole
in it reads as a chain nobody understood.

**Matching is retrieve-then-rerank, on what a company does rather than what it is called.**
Word overlap over five hundred business descriptions is instant and a poor judge — it has no
synonymy, so a tier for OSAT never reaches a company describing "assembly and test". A model
reading five hundred descriptions is the opposite problem: it does not fit. So overlap casts
wide and a matcher decides which of the shortlist genuinely supply the tier.

The first version of this
module searched company names and NSE industry codes, and it was wrong in a way that a
measurement made obvious: against the exchange's own NIFTY INDIA DEFENCE membership — all
nineteen constituents present and available to be found — it found three. A name is branding,
and seventeen of those nineteen file under "Capital Goods" alongside cement plants.

So matching reads a company's **business description** and its granular industry. Hindustan
Aeronautics does not say "defence" in its name; its description says it designs and
manufactures aircraft, helicopters and aero-engines, and it classifies as `Aerospace & Defense`.

**Two ways a company reaches a tier, and they are not equally strong.** A company that
*discussed* the theme in its own commentary has said so itself; a company matched on its
description has been read about. Both are offered, both carry which of the two they are, and
nothing here converts one into the other.
"""

from __future__ import annotations

import logging
import re

from app.data.protocols import UniverseSnapshot
from app.domain.themes import Candidate, Exposure, Reference, UnresolvedTier

log = logging.getLogger(__name__)

#: Words that carry no discriminating power in a supplier description.
STOPWORDS = frozenset(
    {
        "and", "or", "of", "the", "a", "an", "for", "with", "to", "in", "its", "that",
        "company", "companies", "firm", "firms", "manufacturer", "manufacturers",
        "manufacturing", "provider", "providers", "supplier", "suppliers", "producer",
        "producers", "operator", "operators", "vendor", "vendors", "maker", "makers",
        "services", "service", "systems", "system", "solutions", "solution",
        "equipment", "products", "product", "industry", "industries", "sector",
        "large", "scale", "specialized", "specialised", "high", "grade", "various",
        "related", "other", "also", "including", "include", "includes",
        # Marketing vocabulary. These appear in company descriptions *and* in supplier
        # descriptions, so they match constantly and discriminate never -- a tier described
        # as "a leading provider of back-end manufacturing for the global semiconductor
        # industry" scored `global` and `leading` against half the universe and put the one
        # company that actually does the work fourth.
        "leading", "global", "premier", "trusted", "renowned", "innovative", "foremost",
        "reputed", "world", "class", "range", "wide", "well", "known", "major", "across",
    }
)

MIN_TERM_LENGTH = 4

#: Candidates per description. Generous, and truncation is *reported* when it bites.
#:
#: A tight cap looked prudent and was actively harmful. Thirteen defence companies matched a
#: tier on exactly two terms each — a perfect tie — and a cap of eight cut the tail
#: alphabetically, silently dropping Hindustan Aeronautics, Garden Reach, Paras and Zen
#: because H, G, P and Z sort late. Losing the largest defence manufacturer in India to
#: alphabetical order is the kind of wrong-but-plausible output that ends trust in a tool.
MAX_PER_DESCRIPTION = 25

#: Term hits needed to enter the shortlist. **One**, because this is now a *recall* step whose
#: only job is to be generous: a matcher reads the shortlist afterwards and decides. Requiring
#: two was right when overlap was the final judge and is wrong now — it would exclude the
#: company whose description says "assembly and test" from a tier called OSAT before anything
#: capable of recognising the synonym ever saw it.
MIN_TERM_HITS = 1

#: Shortlist size. Generous, because precision comes later and the cost of an extra candidate
#: is one line in a prompt.
SHORTLIST = 40

#: Characters of description handed to the matcher per company. A budget rather than a prefix
#: -- see `focused_excerpt`, which spends it on the sentences that answered the query.
MATCHER_EXCERPT_CHARS = 700

_SENTENCE = re.compile(r"(?<=[.;])\s+")


def focused_excerpt(description: str, hits: set[str], limit: int = MATCHER_EXCERPT_CHARS) -> str:
    """The sentences that answered the query, plus the one that says who the company is.

    **Replaces handing the matcher the first N characters, which was silently wrong.** CG Power
    describes itself over seventeen hundred characters; the sentence that decides whether it
    supplies a semiconductor assembly tier -- "the company offers semiconductor design,
    outsourced semiconductor assembly and testing" -- begins at character 938. Truncating at a
    prefix meant the precision step could not see the single fact it existed to judge, and it
    correctly answered "no" to a question it had not been shown.

    That failure is not an edge case. A theme exposure is usually a *segment*, and a company
    describes its segments after it has described itself, so a prefix systematically hides
    exactly the companies whose exposure is partial -- which is most of them.

    The first sentence is always kept, because "which company is this" is context the matched
    sentences do not carry on their own.
    """
    text = " ".join((description or "").split())
    if not text:
        return ""
    if len(text) <= limit:
        return text

    sentences = _SENTENCE.split(text)
    if not sentences:
        return text[:limit]

    kept = [sentences[0]]
    used = len(sentences[0])
    for sentence in sentences[1:]:
        lowered = sentence.lower()
        if not any(hit in lowered for hit in hits):
            continue
        if used + len(sentence) + 1 > limit:
            break
        kept.append(sentence)
        used += len(sentence) + 1

    return " ".join(kept)[:limit]


def terms(description: str) -> list[str]:
    """The discriminating words in a supplier description."""
    words = re.findall(r"[a-z]+", (description or "").lower())
    seen: dict[str, None] = {}
    for word in words:
        if len(word) >= MIN_TERM_LENGTH and word not in STOPWORDS:
            seen.setdefault(word, None)
    return list(seen)


def match_description(
    description: str,
    universe: UniverseSnapshot,
    profiles=None,
    limit: int | None = None,
) -> tuple[list[tuple[str, str]], str | None]:
    """Instruments whose *business* matches a supplier description.

    Returns ``(matches, reason_when_none)``, each match being ``(symbol, why)``.

    Scored by how many distinct query terms the company's description contains, because with
    several hundred words of prose to search, one shared word is a coincidence and three is a
    subject in common. Ordering is by that count — **a match-quality ordering, not a merit
    one**. It says how well a description answered the query and nothing whatever about the
    company as an investment; nothing downstream may read it as a ranking.
    """
    wanted = terms(description)
    if not wanted:
        return [], "no discriminating terms"
    if profiles is None:
        return [], "no company profiles available to match against"

    scored: list[tuple[int, str, str]] = []
    for instrument in universe.instruments:
        profile = profiles.get(instrument.symbol)
        haystack = profile.searchable if profile is not None else ""
        if not haystack:
            continue
        hits = [term for term in wanted if term in haystack]
        if len(hits) >= MIN_TERM_HITS:
            scored.append((len(hits), instrument.symbol, ", ".join(hits[:4])))

    if not scored:
        return [], None

    scored.sort(key=lambda row: (-row[0], row[1]))
    kept = scored[:limit or MAX_PER_DESCRIPTION]
    note = (
        f"showing {len(kept)} of {len(scored)} matches"
        if len(scored) > len(kept)
        else None
    )
    return [(symbol, why) for _, symbol, why in kept], note


def resolve_tier(
    theme_key: str,
    tier: int,
    label: str,
    supplier_descriptions: list[str],
    universe: UniverseSnapshot,
    references: list[Reference] | None = None,
    notable_examples: list[dict] | None = None,
    profiles=None,
    matcher=None,
    reasoning: str = "",
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

    # Path two: shortlist by word overlap, then let a matcher decide which of those actually
    # supply the tier. Overlap alone cannot tell that "assembly and test" is OSAT; a matcher
    # cannot read five hundred descriptions. Each does the half it is good at.
    unresolved: list[str] = []
    truncations: list[str] = []
    shortlist: dict[str, str] = {}

    for description in supplier_descriptions or []:
        matches, note = match_description(description, universe, profiles, limit=SHORTLIST)
        if not matches:
            unresolved.append(f"{description} ({note})" if note else description)
            continue
        if note:
            log.info("tier %s: %s for %r", tier, note, description)
            truncations.append(f"{description}: {note}")
        for symbol, why in matches:
            shortlist.setdefault(symbol, f"{description} ({why})")

    if shortlist and matcher is not None:
        # Every word the tier asked about. The matcher is shown the sentences containing
        # these rather than a prefix, because the sentence that decides a diversified
        # company's exposure is the one describing the relevant segment, and that is never
        # in the first paragraph.
        asked = {term for d in supplier_descriptions or [] for term in terms(d)}
        decided = matcher(
            label or (supplier_descriptions or [""])[0],
            reasoning or "",
            [
                {
                    "symbol": symbol,
                    "description": focused_excerpt(profiles[symbol].searchable, asked),
                }
                for symbol in shortlist
                if profiles and symbol in profiles
            ],
        )
        if decided is not None:
            # A matcher that answered replaces the shortlist entirely: the overlap step was
            # recall and was never meant to be an answer.
            for symbol, why in decided.items():
                if symbol in candidates:
                    continue
                candidates[symbol] = Candidate(
                    symbol=symbol,
                    theme_key=theme_key,
                    tier=tier,
                    exposure=Exposure.UNESTABLISHED,
                    exposure_basis=f"read as supplying this tier: {why}",
                    matched_description=shortlist.get(symbol),
                )
        else:
            # The matcher could not answer. Falling back to the shortlist is more useful than
            # an empty tier, and the basis says plainly that nothing read it.
            for symbol, description in shortlist.items():
                if symbol in candidates:
                    continue
                candidates[symbol] = Candidate(
                    symbol=symbol,
                    theme_key=theme_key,
                    tier=tier,
                    exposure=Exposure.UNESTABLISHED,
                    exposure_basis=(
                        f"business description overlaps {description}; not read by a matcher"
                    ),
                    matched_description=description,
                )
    else:
        for symbol, description in shortlist.items():
            if symbol in candidates:
                continue
            candidates[symbol] = Candidate(
                symbol=symbol,
                theme_key=theme_key,
                tier=tier,
                exposure=Exposure.UNESTABLISHED,
                exposure_basis=f"business description overlaps {description}",
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
    reason = "no company's business description matched this tier"
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
    profiles=None,
    matcher=None,
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
            profiles=profiles,
            matcher=matcher,
            reasoning=str(tier.get("reasoning") or ""),
        )
        candidates.extend(found)
        if missing is not None:
            unresolved.append(missing)

    return candidates, unresolved

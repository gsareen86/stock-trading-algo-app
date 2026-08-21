"""How well a company's connection to a theme is actually established.

Three grades and no number, deliberately. A number would be sortable, and sorting candidates by
theme exposure is a ranking this platform does not permit — it would become "the top five theme
plays", which is a recommendation wearing a measurement's clothes.

**The grades are ordered by what supports them, not by strength of belief:**

* `established` — the company's own business description names the activity. It has told the
  world, in its filing prose, that this is what it does.
* `claimed` — its management discussed the theme in commentary. It said so; nothing corroborates
  the scale.
* `unestablished` — neither. Its industry looked right, or a search proposed it. Still listed,
  because an honest "we could not establish this" is a real answer and hiding the name would be
  a worse one.

**Grading costs a request, so it is never speculative.** The financials provider allows 500 a
month; grading a whole chain on the chance someone looks at it would spend the allowance on
names nobody opened. Exposure is established for the candidates a reader actually asks about,
and every other candidate keeps the grade resolution gave it.
"""

from __future__ import annotations

import logging
import re

from app.domain.financials import CompanyFinancials
from app.domain.themes import Candidate, Exposure, Reference

#: Reused from resolution so a term that discriminates in one place discriminates in the other.
from app.themes.resolve import MIN_TERM_LENGTH, STOPWORDS

#: Distinct terms a description must contain before it *establishes* exposure.
#:
#: Two, not one, and the difference is the whole grade. One shared word between a theme label
#: and several hundred words of prose is a coincidence — "power" appears in the description of
#: every utility, and promoting one of them to the strongest grade on that basis says something
#: the platform cannot support. Resolution has required two since it started reading
#: descriptions; grading requiring one was an inconsistency that made `established` the easiest
#: grade to earn rather than the hardest.
MIN_ESTABLISHING_HITS = 2

log = logging.getLogger(__name__)

#: How much of a description to quote back as the basis. Enough to judge, short enough to read.
BASIS_WIDTH = 220


def theme_terms(*phrases: str) -> list[str]:
    """Discriminating words from a theme label and its supplier descriptions."""
    seen: dict[str, None] = {}
    for phrase in phrases:
        for word in re.findall(r"[a-z]+", (phrase or "").lower()):
            if len(word) >= MIN_TERM_LENGTH and word not in STOPWORDS:
                seen.setdefault(word, None)
    return list(seen)


def _quote(description: str, term: str) -> str:
    """The text around a matched term, so a grade can be judged without the document.

    Snapped to word boundaries. A window cut by character count lands mid-word — "ices Ltd is
    an India-based company" — which reads as a broken excerpt rather than a shortened one, and
    a reader who cannot trust the quotation will not trust the grade either.
    """
    lowered = description.lower()
    at = lowered.find(term)
    if at < 0:
        return _ellipsis(
            description[:BASIS_WIDTH], before=False, after=len(description) > BASIS_WIDTH
        )

    start = max(0, at - BASIS_WIDTH // 2)
    end = min(len(description), at + len(term) + BASIS_WIDTH // 2)

    # Grow outwards to the nearest space so neither edge splits a word.
    while start > 0 and not description[start - 1].isspace():
        start -= 1
    while end < len(description) and not description[end].isspace():
        end += 1

    text = re.sub(r"\s+", " ", description[start:end]).strip()
    return _ellipsis(text, before=start > 0, after=end < len(description))


def _ellipsis(text: str, before: bool, after: bool) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return f"{'…' if before else ''}{text}{'…' if after else ''}"


def grade(
    candidate: Candidate,
    theme_label: str,
    financials: CompanyFinancials | None = None,
    references: list[Reference] | None = None,
    supplier_descriptions: list[str] | None = None,
) -> Candidate:
    """Re-grade one candidate against everything now known about it.

    Never lowers a grade. A candidate already `claimed` because its management discussed the
    theme does not become `unestablished` because a description lookup failed — the commentary
    still happened, and a provider being unavailable is not evidence about the company.
    """
    terms = theme_terms(theme_label, *(supplier_descriptions or []))

    # Strongest first: the company's own description of its business names the activity.
    description = (financials.description or "") if financials else ""
    if description and terms:
        lowered = description.lower()
        hits = [term for term in terms if term in lowered]
        if len(hits) >= MIN_ESTABLISHING_HITS:
            named = ", ".join(hits[:3])
            return _with(
                candidate,
                Exposure.ESTABLISHED,
                f"business description names {named}: “{_quote(description, hits[0])}”",
            )

    # Next: it said so itself, in commentary.
    spoken = next(
        (r for r in (references or []) if r.symbol == candidate.symbol), None
    )
    if spoken is not None:
        return _with(
            candidate,
            Exposure.CLAIMED,
            f"discussed the theme in {spoken.period} ({spoken.kind.value})",
        )

    # Nothing new. Keep whatever resolution decided, including its reason.
    return candidate


def _with(candidate: Candidate, exposure: Exposure, basis: str) -> Candidate:
    """Apply a grade, refusing to move a candidate *down* the scale."""
    order = {Exposure.UNESTABLISHED: 0, Exposure.CLAIMED: 1, Exposure.ESTABLISHED: 2}
    if order[exposure] <= order[candidate.exposure]:
        return candidate
    return Candidate(
        symbol=candidate.symbol,
        theme_key=candidate.theme_key,
        tier=candidate.tier,
        exposure=exposure,
        exposure_basis=basis,
        matched_description=candidate.matched_description,
    )


def grade_many(
    candidates: list[Candidate],
    theme_label: str,
    financials_source=None,
    references: list[Reference] | None = None,
    supplier_descriptions: list[str] | None = None,
    limit: int | None = None,
) -> list[Candidate]:
    """Grade a set of candidates, spending at most ``limit`` provider requests.

    ``limit`` exists because this is the only part of the theme engine that costs a metered
    request per company. Absent, it grades everything asked of it; the caller decides, because
    only the caller knows whether a reader is looking at one name or a whole chain.
    """
    from app.domain.instrument import Instrument

    graded: list[Candidate] = []
    spent = 0

    for candidate in candidates:
        financials = None
        may_spend = limit is None or spent < limit
        if financials_source is not None and may_spend:
            try:
                financials = financials_source.financials(Instrument(candidate.symbol))
                spent += 1
            except Exception as exc:
                # A provider failure is not evidence about the company. Grade on what is left.
                log.warning("financials lookup failed for %s: %s", candidate.symbol, exc)

        graded.append(
            grade(
                candidate,
                theme_label,
                financials=financials,
                references=references,
                supplier_descriptions=supplier_descriptions,
            )
        )

    return graded

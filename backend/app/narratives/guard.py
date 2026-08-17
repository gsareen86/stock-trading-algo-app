"""The numeric guard.

The one rule that makes a generated narrative trustworthy: **every number in the prose must
be one the verdict already established.** A plausible invented figure sitting inside otherwise
accurate text is worse than no narrative at all, because it reads exactly like the traceable
parts and there is nothing in the sentence to mark it as different.

The guard fails closed. Anything it cannot confidently trace is a rejection, and a rejection
discards the whole narrative rather than editing it — see `design.md` §3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.verdict import Verdict

#: Numbers as they appear in prose: optional currency sign, comma grouping, decimals, and a
#: trailing unit that is part of the figure rather than a separate number (%, x, bps).
#: Deliberately greedy about what counts as a number — a form this misses is a form that
#: could carry an invented figure past the guard.
_NUMBER = re.compile(
    r"""
    (?<![\w.])                 # not mid-identifier and not a decimal tail
    -?                         # sign
    (?:₹|Rs\.?\s?|\$)?         # currency
    (\d{1,3}(?:,\d{2,3})+|\d+) # grouped (Indian or Western) or plain digits
    (?:\.(\d+))?               # decimal part
    \s?(?:%|x|X|bps)?          # unit that belongs to the figure
    (?![\w.])
    """,
    re.VERBOSE,
)

#: Inline citations the prompt asks for, e.g. `[rs_63d]`.
_CITATION = re.compile(r"\[([a-zA-Z0-9_.:-]+)\]")

#: Dates are not measurements, and their components are not claims about the instrument.
#: Removed before extraction so `2026-08-17` cannot contribute an `8` that has to be traced.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")

#: No allowance for "structural" small numbers. An exemption for 1-3 would let "up 2%" through
#: invented, which is precisely the failure this guard exists for. Ordinals (`1st`), list
#: markers (`1.`) and spelled-out words are already excluded by the pattern's boundaries, so
#: the exemption would buy nothing and cost the guarantee.


@dataclass(frozen=True, slots=True)
class GuardResult:
    """Why a narrative was accepted or rejected. Never an exception."""

    ok: bool
    #: Figures found in the prose that no evidence row supports.
    untraceable: tuple[float, ...] = ()
    #: Cited evidence ids that do not exist on the verdict.
    unknown_citations: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        parts = []
        if self.untraceable:
            figures = ", ".join(_render(n) for n in self.untraceable)
            parts.append(f"numbers not present in the evidence: {figures}")
        if self.unknown_citations:
            parts.append(f"cited evidence that does not exist: {', '.join(self.unknown_citations)}")
        return "; ".join(parts) or "ok"


def _render(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def numbers_in(text: str) -> list[float]:
    """Every figure stated in prose, in order of appearance."""
    found: list[float] = []
    for match in _NUMBER.finditer(text):
        whole = match.group(1).replace(",", "")
        decimals = match.group(2)
        raw = f"{whole}.{decimals}" if decimals else whole
        try:
            value = float(raw)
        except ValueError:  # pragma: no cover - the pattern cannot produce this
            continue
        found.append(-value if match.group(0).lstrip().startswith("-") else value)
    return found


def traces_to(stated: float, allowed: set[float]) -> bool:
    """Whether a figure in prose is a faithful rendering of some allowed value.

    Matching is by *shortening*, not equality: evidence carries 12.437 and readable prose says
    12.4. A stated figure is accepted when some allowed value either rounds **or truncates** to
    it at the precision the prose used.

    Truncation is accepted because writers — human and model alike — produce it constantly, and
    it was the first thing a real model did here: given 5.2968 it wrote 5.29, which rounding
    alone rejects. Both operations stay inside one unit of the stated precision, so neither can
    express a claim the evidence does not support; an invented figure would have to land within
    a hair of a real one to pass, which is not invention in any sense worth guarding against.

    Exact equality would reject every well-written narrative; a fixed epsilon would accept a
    figure that is merely nearby, which on a volatile day is a different claim entirely.
    """
    decimals = _decimals_of(stated)
    target = round(stated, decimals)
    return any(
        round(candidate, decimals) == target or _truncate(candidate, decimals) == target
        for candidate in allowed
    )


def _truncate(value: float, decimals: int) -> float:
    scale = 10**decimals
    return int(value * scale) / scale


def _decimals_of(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 0
    _, _, fraction = text.partition(".")
    return 0 if fraction == "0" else len(fraction)


def check(narrative: str, verdict: Verdict) -> GuardResult:
    """Validate generated prose against what the verdict actually established."""
    allowed = verdict.citable_numbers
    known_ids = {row.id for row in verdict.evidence}

    unknown = tuple(
        cited for cited in _CITATION.findall(narrative) if cited not in known_ids
    )

    # Citations and dates are identifiers, not claims. Stripping them first stops an id like
    # `[ma-200]` or a timestamp from contributing digits that would then have to be traced.
    prose = _ISO_DATE.sub(" ", _CITATION.sub(" ", narrative))
    untraceable = tuple(
        stated for stated in numbers_in(prose) if not traces_to(stated, allowed)
    )
    return GuardResult(
        ok=not untraceable and not unknown,
        untraceable=untraceable,
        unknown_citations=unknown,
    )

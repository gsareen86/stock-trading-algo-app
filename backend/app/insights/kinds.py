"""What kinds of insight exist, and how loud each one is.

**Severity belongs to the kind, not to the item.** Declaring it here — once, up front — is what
stops it becoming a number computed per insight and compared across kinds, which is a ranking,
which is the confluence scorecard arriving at the last layer where it would look helpful.

The suppression window is also per kind, for the same reason it has to exist at all: a daily
cycle regenerates the same observations every morning, and a feed that repeats itself is one
people learn to scroll past. A broken thesis is worth restating weekly. A regime change is not
worth restating until the regime changes back.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


#: High first — the per-cycle cap fills in this order.
SEVERITY_ORDER = (Severity.HIGH, Severity.MEDIUM, Severity.LOW)


class Kind(StrEnum):
    """Every insight the platform can raise."""

    #: The strategy that justified a holding now says AVOID.
    THESIS_BROKEN = "thesis_broken"
    #: A holding exceeds the concentration cap.
    CONCENTRATION = "concentration"
    #: Earnings or a corporate action is due on something held.
    EVENT_DUE = "event_due"
    #: News or a filing on something held. Quoted from a tool, never measured.
    POSITION_NEWS = "position_news"
    #: Risk assessed a verdict as actionable.
    OPPORTUNITY = "opportunity"
    #: The book is at its position limit, so opportunities cannot be acted on.
    BOOK_FULL = "book_full"
    #: The market regime changed.
    REGIME_CHANGE = "regime_change"


@dataclass(frozen=True, slots=True)
class KindSpec:
    severity: Severity
    #: Days before the same dedupe key may be raised again.
    suppress_days: int
    #: True when the body is quoted from a tool rather than measured by this platform.
    from_research: bool = False


SPECS: dict[Kind, KindSpec] = {
    # The single most actionable thing the platform can notice, and only noticeable by
    # joining verdicts to positions. Restated weekly while it stays true.
    Kind.THESIS_BROKEN: KindSpec(Severity.HIGH, suppress_days=7),
    Kind.CONCENTRATION: KindSpec(Severity.HIGH, suppress_days=7),
    Kind.EVENT_DUE: KindSpec(Severity.MEDIUM, suppress_days=3, from_research=True),
    Kind.POSITION_NEWS: KindSpec(Severity.MEDIUM, suppress_days=2, from_research=True),
    Kind.OPPORTUNITY: KindSpec(Severity.MEDIUM, suppress_days=3),
    Kind.BOOK_FULL: KindSpec(Severity.LOW, suppress_days=7),
    # Not worth restating until the regime changes back — which changes the dedupe key.
    Kind.REGIME_CHANGE: KindSpec(Severity.LOW, suppress_days=30),
}


def spec(kind: Kind) -> KindSpec:
    return SPECS[kind]

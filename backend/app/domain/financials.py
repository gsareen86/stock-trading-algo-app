"""What kind of business a company is.

Separate from `QuarterlyFundamentals`, which stays four fields wide because `fun_tech_momentum`
needs quarterly EPS and revenue and nothing else. Widening that seam would put a hundred
optional fields in front of the one strategy that reads it, almost all of them null almost all
of the time. This is the wide seam; that one is untouched and does not know this exists.

**Nothing here is a judgement.** A metric carries its value, its label and where it came from.
Whether ROE of 15% is good, and whether it is good *for a bank*, is a threshold applied in
`discovery-funnel` — and applied as a facet, never as a gate that would stop a price-and-volume
strategy from ever seeing the name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

#: Provider metric keys arrive with stray closing parentheses on about one in twenty names —
#: `returnOnAverageEquityMostRecentFiscalYear)`, `inventoryTurnoverTrailing12Month)`. Observed
#: in a real response, not guessed at. Matching on the raw key would silently miss those
#: metrics for those companies, which is the worst kind of gap: partial and unannounced.
_KEY_NOISE = re.compile(r"[()\s]+")


def normalise_key(key: str) -> str:
    """Provider key to a stable lookup key.

    `revenuePerShare(5yrGrowth)` becomes `revenuepershare5yrgrowth`.
    """
    return _KEY_NOISE.sub("", key or "").lower()


@dataclass(frozen=True, slots=True)
class Metric:
    """One reported figure, and where it came from."""

    key: str
    label: str
    value: float | None
    category: str
    source: str
    #: Populated only when the platform computed this rather than receiving it. Named inputs
    #: are what let a wrong number be traced to bad arithmetic or a bad input, rather than
    #: leaving both suspects.
    derived_from: tuple[str, ...] = ()

    @property
    def is_derived(self) -> bool:
        return bool(self.derived_from)

    @property
    def available(self) -> bool:
        """A null from the provider means *not reported*, and it is never zero.

        Interest coverage comes back null for companies with no debt. Reading that as 0.0
        would rank a debt-free company as the most fragile business in the index.
        """
        return self.value is not None


@dataclass(frozen=True, slots=True)
class PeriodValue:
    """One figure for one reporting period."""

    #: The provider's own label, e.g. `Mar 2026` or `Jun 2026`. Kept verbatim so a figure can
    #: always be traced back to the row it was read from.
    period: str
    value: float
    period_end: date | None = None


@dataclass(frozen=True, slots=True)
class StatementSeries:
    """One line item across periods, **most recent first**.

    The ordering is part of the contract, exactly as it is for `QuarterlyFundamentals`: every
    comparison made against it is "latest versus something older", and a caller reversing the
    list is the off-by-one that silently inverts a growth test.
    """

    metric: str
    points: tuple[PeriodValue, ...] = ()

    def latest(self) -> float | None:
        return self.points[0].value if self.points else None

    def at(self, index: int) -> float | None:
        return self.points[index].value if len(self.points) > index else None


@dataclass(frozen=True, slots=True)
class Shareholding:
    """Who owns the company, as filed for one quarter.

    **Two providers report two different bucketings of the same thing, and conflating them is
    silently wrong.** The company endpoint reports promoter, FII, *mutual fund* and a residual
    "other"; the shareholding-history endpoint reports promoter, FII, *DII*, government and
    public. Mutual funds are a subset of domestic institutions — for one real company the two
    read 5.68 and 13.41 for what looks like the same row.

    So each field means exactly one thing and is populated only by a source that reports it.
    A field left `None` means this reading did not carry it, never that it is zero.
    """

    as_of: date
    promoter_pct: float | None = None
    fii_pct: float | None = None
    #: All domestic institutions. Only the shareholding-history endpoint reports this.
    dii_pct: float | None = None
    #: Mutual funds and insurance alone — a *subset* of `dii_pct`, never a substitute for it.
    mutual_fund_pct: float | None = None
    government_pct: float | None = None
    public_pct: float | None = None
    #: The company endpoint's residual bucket: everything that is not promoter, FII or MF.
    #: Not comparable to `public_pct`, which excludes non-MF domestic institutions.
    other_pct: float | None = None
    #: **Not served by the financials provider.** Promoter pledge is a governance fact worth
    #: gating on and it is absent here rather than zero — `None` means nobody told us, which
    #: is a different claim from "nothing is pledged". Sourcing it needs exchange filings.
    pledge_pct: float | None = None
    source: str = ""


@dataclass(frozen=True, slots=True)
class CompanyFinancials:
    """Everything the wide seam knows about one company at one moment."""

    symbol: str
    #: Keyed by `normalise_key`, so a provider typo cannot hide a metric.
    metrics: dict[str, Metric] = field(default_factory=dict)
    statements: dict[str, StatementSeries] = field(default_factory=dict)
    shareholding: tuple[Shareholding, ...] = ()
    industry: str | None = None
    company_name: str | None = None
    peers: tuple[str, ...] = ()
    source: str = ""
    fetched_at: datetime | None = None
    #: Set when the seam could not answer, saying why — a missing key and a throttled provider
    #: are different problems and a caller may want to say which.
    unavailable_reason: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.metrics and not self.statements and not self.shareholding

    def metric(self, key: str) -> Metric | None:
        return self.metrics.get(normalise_key(key))

    def value(self, key: str) -> float | None:
        found = self.metric(key)
        return found.value if found else None

    def latest_shareholding(self) -> Shareholding | None:
        return self.shareholding[0] if self.shareholding else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "industry": self.industry,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "unavailable_reason": self.unavailable_reason,
            "metrics": {
                k: {
                    "label": m.label,
                    "value": m.value,
                    "category": m.category,
                    "derived_from": list(m.derived_from),
                }
                for k, m in self.metrics.items()
            },
            "shareholding": [
                {
                    "as_of": s.as_of.isoformat(),
                    "promoter_pct": s.promoter_pct,
                    "fii_pct": s.fii_pct,
                    "dii_pct": s.dii_pct,
                    "pledge_pct": s.pledge_pct,
                }
                for s in self.shareholding
            ],
        }


def empty(symbol: str, reason: str | None = None) -> CompanyFinancials:
    return CompanyFinancials(symbol=symbol, unavailable_reason=reason)


#: `Mar 2026`, `Jun 2026` — the provider's period labels. Parsed to the month end so periods
#: can be ordered; the original label travels alongside for traceability.
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_period(label: str) -> date | None:
    """`Mar 2026` → 2026-03-31. Unparseable labels resolve to nothing, never to a guess."""
    parts = (label or "").strip().split()
    if len(parts) != 2:
        return None
    month = _MONTHS.get(parts[0][:3].lower())
    if month is None or not parts[1].isdigit():
        return None
    year = int(parts[1])
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)

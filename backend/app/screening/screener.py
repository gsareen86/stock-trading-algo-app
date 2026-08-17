"""Applying the filters to a universe.

The screen returns the eligible set **in universe order**, with a reason for everything it
removed. It does not rank. Ordering survivors by anything resembling quality would be a
cross-strategy score one layer above the strategies, where nobody would think to look for the
thing this rebuild exists to remove.

Nothing here raises. An instrument whose history cannot be fetched is excluded with that as its
reason, which is information; a screen that dies on one bad symbol is not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.clock import now_ist
from app.data.protocols import PriceSource, UniverseSnapshot
from app.data.surveillance import SurveillanceList
from app.data.surveillance import load as load_surveillance
from app.domain.instrument import Instrument
from app.domain.verdict import Evidence
from app.screening import filters

log = logging.getLogger(__name__)

#: Enough history for the longest lookback any strategy uses, plus the turnover window.
SCREEN_LOOKBACK_DAYS = 400


@dataclass(frozen=True, slots=True)
class Exclusion:
    """One name the screen removed, and exactly why."""

    symbol: str
    filter_id: str
    reason: str
    evidence: Evidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "filter": self.filter_id,
            "reason": self.reason,
            "evidence": self.evidence.as_dict(),
        }


@dataclass
class ScreenResult:
    """What survived, what did not, and the state of the data behind it."""

    eligible: list[Instrument] = field(default_factory=list)
    excluded: list[Exclusion] = field(default_factory=list)
    considered: int = 0
    universe_origin: str = "unknown"
    index_name: str = ""
    surveillance: dict[str, Any] = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return [i.symbol for i in self.eligible]

    def excluded_by(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.excluded:
            counts[item.filter_id] = counts.get(item.filter_id, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "eligible": self.symbols,
            "eligible_count": len(self.eligible),
            "excluded_count": len(self.excluded),
            # Per-filter counts make "the screen returned eleven names" diagnosable without
            # re-running it with filters commented out one at a time.
            "excluded_by": self.excluded_by(),
            "excluded": [e.as_dict() for e in self.excluded],
            "universe": {"origin": self.universe_origin, "index": self.index_name},
            "surveillance": self.surveillance,
        }


@dataclass(frozen=True, slots=True)
class ScreenCriteria:
    """The floors a name must clear. Defaults live in `filters`."""

    min_turnover_inr: float = filters.DEFAULT_MIN_TURNOVER_INR
    min_price_inr: float = filters.DEFAULT_MIN_PRICE_INR
    min_bars: int = filters.DEFAULT_MIN_BARS
    exclude_surveillance: bool = True
    #: Cap on names returned. Applied *after* filtering and in universe order — a limit, not a
    #: ranking. Zero or None means no cap.
    limit: int | None = None


class Screener:
    """Applies eligibility filters across a universe."""

    def __init__(
        self,
        price_source: PriceSource,
        surveillance: SurveillanceList | None = None,
    ) -> None:
        self._prices = price_source
        self._surveillance = surveillance if surveillance is not None else load_surveillance()

    def run(
        self,
        snapshot: UniverseSnapshot,
        criteria: ScreenCriteria | None = None,
        today: date | None = None,
    ) -> ScreenResult:
        criteria = criteria or ScreenCriteria()
        today = today or now_ist().date()

        result = ScreenResult(
            considered=len(snapshot.instruments),
            universe_origin=snapshot.origin,
            index_name=snapshot.index_name,
            surveillance=self._surveillance.as_dict(today),
        )

        for instrument in snapshot.instruments:
            exclusion = self._assess(instrument, criteria, today)
            if exclusion is None:
                result.eligible.append(instrument)
            else:
                result.excluded.append(exclusion)

        if criteria.limit:
            # Truncation in universe order. Deliberately not "the best N" — the screen has no
            # notion of best, and inventing one here is how a scorecard grows back.
            dropped = result.eligible[criteria.limit :]
            result.eligible = result.eligible[: criteria.limit]
            for instrument in dropped:
                result.excluded.append(
                    Exclusion(
                        symbol=instrument.symbol,
                        filter_id="limit",
                        reason=f"beyond the requested limit of {criteria.limit}",
                        evidence=Evidence(
                            id="screen_limit",
                            label="Position in universe order",
                            value=criteria.limit,
                            source_ref=f"universe://{snapshot.index_name}",
                        ),
                    )
                )
        return result

    # ── internals ─────────────────────────────────────────────────────────────
    def _assess(
        self, instrument: Instrument, criteria: ScreenCriteria, today: date
    ) -> Exclusion | None:
        """First failing filter, or None when the name is eligible.

        Surveillance is checked first: it needs no price data, so a flagged name costs no
        fetch at all.
        """
        if criteria.exclude_surveillance:
            check = filters.check_surveillance(instrument, self._surveillance, today)
            if not check.passed:
                return Exclusion(instrument.symbol, check.filter_id, check.reason, check.evidence)

        try:
            series = self._prices.history(
                instrument, interval="1d", lookback_days=SCREEN_LOOKBACK_DAYS
            )
        except Exception as exc:  # pragma: no cover - sources are contracted not to raise
            log.warning("screen: price fetch failed for %s: %s", instrument.symbol, exc)
            return Exclusion(
                symbol=instrument.symbol,
                filter_id="history",
                reason=f"price history unavailable: {type(exc).__name__}",
                evidence=Evidence(
                    id="screen_bars",
                    label="Daily sessions available",
                    value=0,
                    threshold=criteria.min_bars,
                    operator=filters.Operator.GTE,
                    passed=False,
                    source_ref=f"price://{instrument.symbol}?interval=1d",
                ),
            )

        for check in (
            filters.check_history(instrument, series, criteria.min_bars),
            filters.check_price(instrument, series, criteria.min_price_inr),
            filters.check_turnover(instrument, series, criteria.min_turnover_inr),
        ):
            if not check.passed:
                return Exclusion(instrument.symbol, check.filter_id, check.reason, check.evidence)
        return None

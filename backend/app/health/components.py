"""Scoring the portfolio's structure.

**This scores the book, not the stocks in it.** The distinction is the whole design: blending
strategy verdicts into a number is the confluence scorecard this platform exists to remove;
measuring how concentrated a book is, how much capital is working and how much sits in broken
theses is a measurement of the portfolio itself.

The consequences of that line, enforced here:

* nothing in this module reads a `conviction`, and nothing takes a `Verdict` as input except
  through the already-computed "which of my holdings have a broken thesis" join;
* there is no per-instrument score, so nothing can be sorted by health;
* every component publishes its own measurement and threshold, so the headline is never the
  only number visible — a single figure invites optimising the figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.position import Position

#: Weights sum to 100. They order guidance too — see `guidance.py`.
WEIGHT_CONCENTRATION = 30
WEIGHT_THESIS = 30
WEIGHT_DIVERSIFICATION = 20
WEIGHT_DEPLOYMENT = 20

#: Targets. Deliberately structural: none of them says anything about which stock is good.
TARGET_MAX_POSITION_PCT = 25.0
TARGET_MIN_POSITIONS = 5
TARGET_DEPLOYMENT_PCT = 60.0
TARGET_MAX_DEPLOYMENT_PCT = 95.0


@dataclass(frozen=True, slots=True)
class Component:
    """One structural property, measured against a declared threshold."""

    id: str
    label: str
    #: 0-100. Higher is healthier.
    score: int
    weight: int
    measurement: float
    threshold: float
    unit: str
    detail: str

    @property
    def healthy(self) -> bool:
        return self.score >= 70

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "score": self.score,
            "weight": self.weight,
            "measurement": round(self.measurement, 2),
            "threshold": self.threshold,
            "unit": self.unit,
            "detail": self.detail,
            "healthy": self.healthy,
        }


def _clamp(value: float) -> int:
    return int(max(0.0, min(100.0, value)))


def _open(positions: list[Position]) -> list[Position]:
    return [p for p in positions if p.is_open]


def concentration(positions: list[Position]) -> Component:
    """How much of the committed capital sits in the largest single name.

    Measured on cost basis rather than market value: concentration is about how much was
    committed, and a number that moves because a position appreciated describes the market
    rather than a decision.
    """
    open_positions = _open(positions)
    total = sum(p.cost_basis for p in open_positions)

    if not open_positions or total <= 0:
        return Component(
            id="concentration",
            label="Concentration",
            score=100,
            weight=WEIGHT_CONCENTRATION,
            measurement=0.0,
            threshold=TARGET_MAX_POSITION_PCT,
            unit="%",
            detail="nothing committed",
        )

    largest = max(open_positions, key=lambda p: p.cost_basis)
    weight = largest.cost_basis / total * 100

    # Full marks at or under target, falling to zero as the book becomes a single name.
    if weight <= TARGET_MAX_POSITION_PCT:
        score = 100
    else:
        span = 100.0 - TARGET_MAX_POSITION_PCT
        score = _clamp(100 * (1 - (weight - TARGET_MAX_POSITION_PCT) / span))

    return Component(
        id="concentration",
        label="Concentration",
        score=score,
        weight=WEIGHT_CONCENTRATION,
        measurement=weight,
        threshold=TARGET_MAX_POSITION_PCT,
        unit="%",
        detail=f"{largest.ticker} is {weight:.1f}% of committed capital",
    )


def diversification(positions: list[Position]) -> Component:
    """How many names carry the book."""
    count = len(_open(positions))
    score = _clamp(count / TARGET_MIN_POSITIONS * 100) if TARGET_MIN_POSITIONS else 100
    return Component(
        id="diversification",
        label="Diversification",
        score=score,
        weight=WEIGHT_DIVERSIFICATION,
        measurement=float(count),
        threshold=float(TARGET_MIN_POSITIONS),
        unit="positions",
        detail=f"{count} open position(s), target at least {TARGET_MIN_POSITIONS}",
    )


def deployment(positions: list[Position], capital: float) -> Component:
    """How much capital is working.

    Penalised at both ends: idle capital earns nothing, and a fully committed book has no room
    to act on anything it finds. Both are structural facts about the book.
    """
    committed = sum(p.cost_basis for p in _open(positions))
    pct = (committed / capital * 100) if capital > 0 else 0.0

    if pct < TARGET_DEPLOYMENT_PCT:
        score = _clamp(pct / TARGET_DEPLOYMENT_PCT * 100)
        detail = f"{pct:.1f}% deployed, below the {TARGET_DEPLOYMENT_PCT:.0f}% target"
    elif pct <= TARGET_MAX_DEPLOYMENT_PCT:
        score = 100
        detail = f"{pct:.1f}% deployed"
    else:
        over = pct - TARGET_MAX_DEPLOYMENT_PCT
        score = _clamp(100 - over * 4)
        detail = f"{pct:.1f}% deployed, leaving little room to act"

    return Component(
        id="deployment",
        label="Deployment",
        score=score,
        weight=WEIGHT_DEPLOYMENT,
        measurement=pct,
        threshold=TARGET_DEPLOYMENT_PCT,
        unit="%",
        detail=detail,
    )


def thesis_integrity(positions: list[Position], broken_tickers: set[str]) -> Component:
    """Share of committed capital whose buying strategy now says AVOID.

    Takes tickers rather than verdicts on purpose. The join between a position and the strategy
    that bought it already exists in `insights.rules`; doing it again here would put verdicts
    inside a portfolio score, which is the boundary this module is defined by.
    """
    open_positions = _open(positions)
    total = sum(p.cost_basis for p in open_positions)

    if not open_positions or total <= 0:
        return Component(
            id="thesis_integrity",
            label="Thesis integrity",
            score=100,
            weight=WEIGHT_THESIS,
            measurement=0.0,
            threshold=0.0,
            unit="%",
            detail="nothing committed",
        )

    broken_value = sum(p.cost_basis for p in open_positions if p.ticker in broken_tickers)
    pct = broken_value / total * 100
    return Component(
        id="thesis_integrity",
        label="Thesis integrity",
        score=_clamp(100 - pct),
        weight=WEIGHT_THESIS,
        measurement=pct,
        threshold=0.0,
        unit="%",
        detail=(
            f"{pct:.1f}% of committed capital is in name(s) whose buying strategy now says AVOID"
            if broken_value
            else "no holding's buying strategy has turned"
        ),
    )

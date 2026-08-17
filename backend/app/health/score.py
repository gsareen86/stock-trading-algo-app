"""The headline score, and what to do about it.

The headline is published **with** its components, never instead of them. A single number
invites optimising the number; a number beside four measurements and their thresholds invites
fixing the one that is low, which is the useful behaviour.

Guidance is deterministic. No model is involved, so every figure in a step comes from the
ledger or a declared threshold — the same guarantee `verdict-narratives` enforces on generated
prose, achieved here by not generating prose at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.position import Position
from app.health import components as comp
from app.health.components import Component

#: Below this a component contributes guidance.
GUIDANCE_THRESHOLD = 70


@dataclass(frozen=True, slots=True)
class Step:
    """One concrete thing to do, attached to the component that produced it."""

    component_id: str
    action: str
    detail: str
    ticker: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component_id,
            "action": self.action,
            "detail": self.detail,
            "ticker": self.ticker,
        }


@dataclass
class HealthReport:
    components: list[Component] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)

    @property
    def score(self) -> int:
        """Weighted mean of the components. Never published without them."""
        total_weight = sum(c.weight for c in self.components)
        if not total_weight:
            return 100
        return round(sum(c.score * c.weight for c in self.components) / total_weight)

    @property
    def band(self) -> str:
        score = self.score
        if score >= 80:
            return "healthy"
        if score >= 60:
            return "watch"
        return "attention"

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "band": self.band,
            # Always present. The headline is not meaningful on its own and is not shipped
            # as though it were.
            "components": [c.as_dict() for c in self.components],
            "guidance": [s.as_dict() for s in self.steps],
        }


def build(
    positions: list[Position],
    capital: float,
    broken_tickers: set[str] | None = None,
) -> HealthReport:
    """Score the book's structure and derive its next steps."""
    broken = broken_tickers or set()
    scored = [
        comp.concentration(positions),
        comp.thesis_integrity(positions, broken),
        comp.diversification(positions),
        comp.deployment(positions, capital),
    ]
    return HealthReport(components=scored, steps=_guidance(scored, positions, broken))


def _guidance(
    scored: list[Component], positions: list[Position], broken: set[str]
) -> list[Step]:
    """Steps from components scoring below threshold, ordered by component weight.

    Ordered by *weight*, not by a per-step score. Scoring individual steps would make them
    comparable to each other, which is a ranking of actions — the same mistake one level down
    from ranking instruments.
    """
    by_id = {c.id: c for c in scored}
    steps: list[Step] = []
    open_positions = [p for p in positions if p.is_open]
    total = sum(p.cost_basis for p in open_positions)

    concentration = by_id["concentration"]
    if concentration.score < GUIDANCE_THRESHOLD and open_positions and total > 0:
        largest = max(open_positions, key=lambda p: p.cost_basis)
        target_value = total * comp.TARGET_MAX_POSITION_PCT / 100
        excess_shares = int((largest.cost_basis - target_value) / largest.average_cost)
        if excess_shares > 0:
            steps.append(
                Step(
                    component_id="concentration",
                    action="trim",
                    ticker=largest.ticker,
                    detail=(
                        f"{largest.ticker} is {concentration.measurement:.1f}% of committed "
                        f"capital against a {comp.TARGET_MAX_POSITION_PCT:.0f}% target. "
                        f"Trimming about {excess_shares} share(s) would bring it back."
                    ),
                )
            )

    thesis = by_id["thesis_integrity"]
    if thesis.score < GUIDANCE_THRESHOLD:
        for position in open_positions:
            if position.ticker not in broken:
                continue
            steps.append(
                Step(
                    component_id="thesis_integrity",
                    action="exit",
                    ticker=position.ticker,
                    detail=(
                        f"{position.ticker} was bought on a strategy that now rates it AVOID. "
                        f"Exiting releases ₹{position.cost_basis:,.0f} of committed capital."
                    ),
                )
            )

    diversification = by_id["diversification"]
    if diversification.score < GUIDANCE_THRESHOLD:
        needed = comp.TARGET_MIN_POSITIONS - int(diversification.measurement)
        steps.append(
            Step(
                component_id="diversification",
                action="review",
                detail=(
                    f"{int(diversification.measurement)} open position(s). "
                    f"{needed} more would reach the target spread. "
                    "The screen and the feed are where candidates come from — this step does "
                    "not name one, because choosing between names is a strategy's job."
                ),
            )
        )

    deployment = by_id["deployment"]
    if deployment.score < GUIDANCE_THRESHOLD:
        steps.append(
            Step(
                component_id="deployment",
                action="review",
                detail=deployment.detail
                + (
                    ". Idle capital earns nothing"
                    if deployment.measurement < comp.TARGET_DEPLOYMENT_PCT
                    else ". A fully committed book cannot act on what it finds"
                ),
            )
        )

    weight_of = {c.id: c.weight for c in scored}
    return sorted(steps, key=lambda s: -weight_of[s.component_id])

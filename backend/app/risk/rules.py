"""Portfolio gates and sizing.

Risk takes a verdict and portfolio state and returns a **decision about acting**: proceed with a
size, or do not proceed with a reason. It never touches the verdict. `Verdict` is frozen and its
only mutator sets a narrative, so a risk rule *cannot* downgrade a BUY to a WATCH — it can only
decline to act on one.

That separation is the point. A strategy answers "is this a good setup"; risk answers "should
this portfolio take it". Collapsing them gives one number that means neither.

**Sizing looks at one verdict at a time.** It never compares two verdicts or allocates between
them. A portfolio layer is exactly where cross-strategy ranking would look reasonable, and it is
the confluence scorecard by another name.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain.position import Book, Position
from app.domain.verdict import Stance, Verdict


class RiskOutcome(StrEnum):
    """What risk decided about acting on one verdict."""

    PROCEED = "proceed"
    #: The verdict was not actionable in the first place — WATCH or AVOID.
    NOT_ACTIONABLE = "not_actionable"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Portfolio constraints. Defaults are conservative and meant to be configured."""

    #: Capital the book is allowed to deploy, in rupees.
    capital_inr: float = 10_00_000.0
    #: Most positions the book may hold at once. Beyond this, attention is the scarce resource.
    max_positions: int = 10
    #: Cap on any one name, as a percentage of capital.
    max_position_pct: float = 15.0
    #: Fraction of capital a single new position may use, before the cap is applied.
    target_position_pct: float = 10.0
    #: Never add to a name already held. Pyramiding is a strategy decision this platform does
    #: not currently make, and silently averaging up would be one made by accident.
    allow_adding: bool = False


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """The outcome for one verdict. The verdict itself is unchanged and unchangeable."""

    ticker: str
    strategy_id: str
    outcome: RiskOutcome
    reason: str
    quantity: int = 0
    notional: float = 0.0
    gate_id: str | None = None

    @property
    def proceed(self) -> bool:
        return self.outcome is RiskOutcome.PROCEED

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "strategy_id": self.strategy_id,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "quantity": self.quantity,
            "notional": self.notional,
            "gate": self.gate_id,
        }


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """What the book currently holds. Read-only input to every rule."""

    book: Book
    positions: tuple[Position, ...] = ()
    prices: dict[str, float] | None = None

    @property
    def open_positions(self) -> tuple[Position, ...]:
        return tuple(p for p in self.positions if p.is_open)

    @property
    def deployed(self) -> float:
        return sum(p.cost_basis for p in self.open_positions)

    def holding(self, ticker: str) -> Position | None:
        return next((p for p in self.open_positions if p.ticker == ticker), None)


def assess(
    verdict: Verdict,
    state: PortfolioState,
    limits: RiskLimits,
    last_price: float | None = None,
) -> RiskDecision:
    """Decide whether to act on one verdict, and at what size.

    Gates are checked before sizing, cheapest and most decisive first. Each returns a named
    gate id so a blocked name says *which* constraint stopped it rather than just "no".
    """
    ticker = verdict.ticker
    base = {"ticker": ticker, "strategy_id": verdict.strategy_id}

    # Only a BUY is a proposal to act. WATCH and AVOID are not blocked — there is nothing to
    # block — and calling them "blocked" would misreport a strategy's own conclusion.
    if verdict.stance is not Stance.BUY:
        return RiskDecision(
            **base,
            outcome=RiskOutcome.NOT_ACTIONABLE,
            reason=f"stance is {verdict.stance.value}, not a proposal to buy",
        )

    held = state.holding(ticker)
    if held is not None and not limits.allow_adding:
        return RiskDecision(
            **base,
            outcome=RiskOutcome.BLOCKED,
            gate_id="already_held",
            reason=f"{held.quantity} already held at ₹{held.average_cost:,.2f}",
        )

    if len(state.open_positions) >= limits.max_positions:
        return RiskDecision(
            **base,
            outcome=RiskOutcome.BLOCKED,
            gate_id="position_count",
            reason=f"book holds {len(state.open_positions)} of {limits.max_positions} allowed",
        )

    if last_price is None or last_price <= 0:
        # Not a judgement about the stock — we cannot size without a price, and guessing one
        # would put a made-up number into a position.
        return RiskDecision(
            **base,
            outcome=RiskOutcome.BLOCKED,
            gate_id="no_price",
            reason="no current price available to size against",
        )

    headroom = limits.capital_inr - state.deployed
    if headroom <= 0:
        return RiskDecision(
            **base,
            outcome=RiskOutcome.BLOCKED,
            gate_id="capital",
            reason=f"₹{state.deployed:,.0f} deployed of ₹{limits.capital_inr:,.0f}",
        )

    notional = _target_notional(verdict, limits, headroom)
    quantity = int(notional // last_price)
    if quantity < 1:
        return RiskDecision(
            **base,
            outcome=RiskOutcome.BLOCKED,
            gate_id="size_too_small",
            reason=(
                f"₹{notional:,.0f} available for this name buys no whole shares "
                f"at ₹{last_price:,.2f}"
            ),
        )

    return RiskDecision(
        **base,
        outcome=RiskOutcome.PROCEED,
        reason=(
            f"{quantity} shares at ₹{last_price:,.2f} "
            f"(₹{quantity * last_price:,.0f}, conviction {verdict.conviction})"
        ),
        quantity=quantity,
        notional=round(quantity * last_price, 2),
    )


def _target_notional(verdict: Verdict, limits: RiskLimits, headroom: float) -> float:
    """Rupees to commit to this name.

    Scaled by **this verdict's own conviction**, which is meaningful only within its strategy —
    and that is all it is used for here. It never compares this conviction to another verdict's,
    because conviction is not cross-strategy comparable and treating it as though it were is
    precisely the blend this platform removed.
    """
    target = limits.capital_inr * (limits.target_position_pct / 100.0)
    cap = limits.capital_inr * (limits.max_position_pct / 100.0)
    scaled = target * (verdict.conviction / 100.0)
    return max(0.0, min(scaled, cap, headroom))

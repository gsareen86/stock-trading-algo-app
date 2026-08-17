"""Acting on an insight.

An insight names a problem; this is how it gets fixed without retyping what the insight already
knows — which is where mistakes happen.

**Quantity is re-derived from the ledger at execution, never taken from the insight.** An
insight raised on Monday saying "you hold 6" may be stale by Wednesday. Its payload is a hint
for display; the input to a fill is always the current position. Same reasoning as deriving a
position from trades rather than storing it: the moment a number can be acted on without being
re-read, it can be acted on while wrong.

Every action executes through `Ledger.fill()` — the one execution boundary, unchanged. There is
no second path, and `preview` is a flag on this function rather than a separate estimator,
because two implementations of "what will this do" is how a preview starts lying.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.books.ledger import Ledger
from app.domain.position import Book, FillSource, Side
from app.health import components as health_components
from app.insights.kinds import Kind

log = logging.getLogger(__name__)


class Action(StrEnum):
    """What can be done about an insight."""

    #: Reduce a position to the concentration target.
    TRIM = "trim"
    #: Close a position entirely.
    EXIT = "exit"
    #: Open a position at the size risk proposed.
    BUY = "buy"
    #: Mark it seen without acting — the honest option for "I looked and I am not acting",
    #: which is otherwise indistinguishable from not having looked.
    REVIEW = "review"


#: Actions belong to the *kind*, not the instance.
ACTIONS_FOR_KIND: dict[Kind, tuple[Action, ...]] = {
    Kind.THESIS_BROKEN: (Action.EXIT, Action.REVIEW),
    Kind.CONCENTRATION: (Action.TRIM, Action.REVIEW),
    Kind.OPPORTUNITY: (Action.BUY, Action.REVIEW),
    Kind.EVENT_DUE: (Action.REVIEW,),
    Kind.POSITION_NEWS: (Action.REVIEW,),
    Kind.BOOK_FULL: (Action.REVIEW,),
    Kind.REGIME_CHANGE: (Action.REVIEW,),
}


def actions_for(kind: str) -> tuple[str, ...]:
    try:
        return tuple(a.value for a in ACTIONS_FOR_KIND[Kind(kind)])
    except ValueError:
        return (Action.REVIEW.value,)


class ActionRefused(ValueError):
    """The action cannot be carried out as described."""


@dataclass(frozen=True, slots=True)
class ActionPlan:
    """What an action would do, derived from current state."""

    action: Action
    ticker: str | None
    side: Side | None
    quantity: int
    price: float | None
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "ticker": self.ticker,
            "side": self.side.value if self.side else None,
            "quantity": self.quantity,
            "price": self.price,
            "description": self.description,
        }


def plan(
    action: Action,
    insight: dict[str, Any],
    ledger: Ledger,
    book: Book,
    last_price: float | None,
) -> ActionPlan:
    """Work out what the action would do, from the ledger rather than the insight."""
    if action is Action.REVIEW:
        return ActionPlan(
            action=action,
            ticker=insight.get("ticker"),
            side=None,
            quantity=0,
            price=None,
            description="Marked as reviewed. Nothing was bought or sold.",
        )

    ticker = insight.get("ticker")
    if not ticker:
        raise ActionRefused(f"{action.value} needs an instrument and this insight names none")

    if action is Action.BUY:
        return _plan_buy(insight, ticker, last_price)

    # trim and exit both act on a holding, so both re-read it.
    position = ledger.position(book, ticker)
    if not position.is_open:
        raise ActionRefused(
            f"no open {book.value} position in {ticker} — it may have been closed since this "
            "insight was raised"
        )

    if action is Action.EXIT:
        quantity = position.quantity
        description = (
            f"Sell all {quantity} {ticker} held at an average cost of "
            f"₹{position.average_cost:,.2f}."
        )
    else:
        quantity = _trim_quantity(ledger, book, position.ticker)
        if quantity <= 0:
            raise ActionRefused(
                f"{ticker} is no longer above the "
                f"{health_components.TARGET_MAX_POSITION_PCT:.0f}% concentration target"
            )
        description = (
            f"Sell {quantity} of {position.quantity} {ticker} to bring it back to about "
            f"{health_components.TARGET_MAX_POSITION_PCT:.0f}% of committed capital."
        )

    if last_price is None or last_price <= 0:
        raise ActionRefused(f"no current price for {ticker} to record a fill against")

    return ActionPlan(
        action=action,
        ticker=ticker,
        side=Side.SELL,
        quantity=quantity,
        price=last_price,
        description=description,
    )


def _plan_buy(insight: dict[str, Any], ticker: str, last_price: float | None) -> ActionPlan:
    """Buy the size risk proposed.

    Quantity comes from the risk decision recorded on the insight because that is a *proposal*
    rather than a remembered fact about the world — but it is re-priced here, since the price
    that mattered when the insight was raised is not the price a fill happens at.
    """
    quantity = int(insight.get("payload", {}).get("quantity") or 0)
    if quantity <= 0:
        raise ActionRefused(f"no proposed size recorded for {ticker}")
    if last_price is None or last_price <= 0:
        raise ActionRefused(f"no current price for {ticker} to record a fill against")

    return ActionPlan(
        action=Action.BUY,
        ticker=ticker,
        side=Side.BUY,
        quantity=quantity,
        price=last_price,
        description=(
            f"Buy {quantity} {ticker} at ₹{last_price:,.2f} "
            f"(₹{quantity * last_price:,.0f}), the size risk proposed."
        ),
    )


def _trim_quantity(ledger: Ledger, book: Book, ticker: str) -> int:
    """Shares to sell to bring a name back to the concentration target."""
    open_positions = [p for p in ledger.positions(book) if p.is_open]
    total = sum(p.cost_basis for p in open_positions)
    position = next((p for p in open_positions if p.ticker == ticker), None)
    if position is None or total <= 0 or position.average_cost <= 0:
        return 0

    target_value = total * health_components.TARGET_MAX_POSITION_PCT / 100
    excess = position.cost_basis - target_value
    if excess <= 0:
        return 0
    return min(position.quantity, int(excess / position.average_cost))


def execute(
    action: Action,
    insight: dict[str, Any],
    ledger: Ledger,
    book: Book,
    last_price: float | None,
    preview: bool = False,
) -> tuple[ActionPlan, dict[str, Any] | None]:
    """Carry out an action, or show exactly what it would do.

    Preview runs the identical derivation and returns before writing — one function, so the
    preview cannot drift from the execution.
    """
    prepared = plan(action, insight, ledger, book, last_price)
    if preview or prepared.side is None or prepared.quantity <= 0:
        return prepared, None

    trade = ledger.fill(
        book,
        prepared.ticker or "",
        prepared.side,
        prepared.quantity,
        prepared.price or 0.0,
        source=FillSource.MANUAL,
        strategy_id=insight.get("payload", {}).get("strategy_id"),
        note=f"insight #{insight.get('id')} · {action.value}",
    )
    return prepared, trade.as_dict()

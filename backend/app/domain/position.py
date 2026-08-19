"""Positions and the trades that produce them.

A **position is derived, never edited.** `Trade` is the record; `Position` is a projection of a
symbol's trade history within one book. Storing quantity and average cost as independently
updatable fields is what makes duplicate ledgers unreconcilable: once a position
can be written directly, a bug or a manual fix leaves a position no sequence of trades explains,
and nothing says which of the two is wrong.

**P&L here is gross.** No brokerage, STT, stamp duty or GST, and no tax treatment. Indian equity
charges are not negligible at swing frequencies, so the honest options were to model them
properly or to be explicit that they are absent; this is the second, and every field says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.core.clock import now_utc


class Book(StrEnum):
    """Which book a position belongs to.

    A parameter, not a subclass. Swing and long-term differ in holding period and in which
    strategies feed them — not in what a position *is*. Adding a third book should be a member
    here and nothing else.
    """

    SWING = "swing"
    LONGTERM = "longterm"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class FillSource(StrEnum):
    """What caused a fill. Recorded so a position's provenance stays answerable."""

    MANUAL = "manual"
    RISK = "risk"
    BACKTEST = "backtest"


@dataclass(frozen=True, slots=True)
class Trade:
    """One paper fill. The unit of record."""

    book: Book
    ticker: str
    side: Side
    quantity: int
    price: float
    executed_at: datetime
    source: FillSource = FillSource.MANUAL
    strategy_id: str | None = None
    note: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            # A zero-quantity trade is not a trade, and a negative one is a side expressed
            # twice — both make the derived position silently wrong.
            raise ValueError(f"trade quantity must be positive, got {self.quantity}")
        if self.price <= 0:
            raise ValueError(f"trade price must be positive, got {self.price}")

    @property
    def value(self) -> float:
        """Gross consideration. Excludes all charges."""
        return self.quantity * self.price

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "book": self.book.value,
            "ticker": self.ticker,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "value": self.value,
            "executed_at": self.executed_at.isoformat(),
            "source": self.source.value,
            "strategy_id": self.strategy_id,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Position:
    """An open or closed holding, derived from trades."""

    book: Book
    ticker: str
    quantity: int
    average_cost: float
    realised_pnl: float
    first_acquired: datetime | None = None
    last_trade_at: datetime | None = None
    trade_count: int = 0

    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    @property
    def cost_basis(self) -> float:
        """Gross cost of the open quantity. Excludes charges."""
        return self.quantity * self.average_cost

    def market_value(self, last_price: float | None) -> float | None:
        return None if last_price is None else self.quantity * last_price

    def unrealised_pnl(self, last_price: float | None) -> float | None:
        """Gross, and ``None`` when no price is available.

        Nullable rather than zero for the same reason LLM cost is: "unknown" and "nothing" are
        different facts, and a zero here would quietly enter a portfolio total.
        """
        if last_price is None or not self.is_open:
            return None
        return (last_price - self.average_cost) * self.quantity

    def unrealised_pct(self, last_price: float | None) -> float | None:
        if last_price is None or not self.is_open or self.average_cost <= 0:
            return None
        return round((last_price / self.average_cost - 1) * 100, 4)

    def as_dict(self, last_price: float | None = None) -> dict[str, Any]:
        return {
            "book": self.book.value,
            "ticker": self.ticker,
            "quantity": self.quantity,
            "average_cost": self.average_cost,
            "cost_basis": self.cost_basis,
            "is_open": self.is_open,
            "last_price": last_price,
            "market_value": self.market_value(last_price),
            # Every P&L figure below is gross of brokerage, STT, stamp duty and GST.
            "realised_pnl_gross": self.realised_pnl,
            "unrealised_pnl_gross": self.unrealised_pnl(last_price),
            "unrealised_pct": self.unrealised_pct(last_price),
            "first_acquired": self.first_acquired.isoformat() if self.first_acquired else None,
            "last_trade_at": self.last_trade_at.isoformat() if self.last_trade_at else None,
            "trade_count": self.trade_count,
        }


def derive_position(book: Book, ticker: str, trades: list[Trade]) -> Position:
    """Fold a symbol's trades into its current position.

    Average cost rather than FIFO lots: lot tracking exists almost entirely to compute tax, and
    computing it without STT, brokerage and the STCG/LTCG distinction would produce a number
    that looks like a tax basis and is not one.

    A sell beyond the held quantity is clamped rather than allowed to go short — this platform
    is long-only, and a negative quantity would silently become a short position nobody opened.
    """
    quantity = 0
    average_cost = 0.0
    realised = 0.0
    first_acquired: datetime | None = None
    last_trade_at: datetime | None = None

    for trade in sorted(trades, key=lambda t: (t.executed_at, t.id or 0)):
        last_trade_at = trade.executed_at
        if trade.side is Side.BUY:
            if quantity == 0:
                first_acquired = trade.executed_at
            total_cost = average_cost * quantity + trade.value
            quantity += trade.quantity
            average_cost = total_cost / quantity if quantity else 0.0
        else:
            sold = min(trade.quantity, quantity)
            realised += (trade.price - average_cost) * sold
            quantity -= sold
            if quantity == 0:
                average_cost = 0.0
                first_acquired = None

    return Position(
        book=book,
        ticker=ticker,
        quantity=quantity,
        average_cost=round(average_cost, 4),
        realised_pnl=round(realised, 2),
        first_acquired=first_acquired,
        last_trade_at=last_trade_at,
        trade_count=len(trades),
    )


def empty_position(book: Book, ticker: str) -> Position:
    return Position(book=book, ticker=ticker, quantity=0, average_cost=0.0, realised_pnl=0.0)


def utc_now() -> datetime:
    return now_utc()

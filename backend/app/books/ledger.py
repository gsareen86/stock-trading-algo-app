"""One ledger, parameterised by book.

Three duplicate position ledgers, one per book, drift — and reconciling them is impossible
because none is authoritative. There is deliberately no
`SwingLedger` here and no base class waiting to be subclassed — swing and long-term differ in
holding period and in which strategies feed them, not in what a position is.

**`fill()` is the only thing in the platform that creates a trade.** Principle 7 exists because
a broker class that looks like it executes and silently does nothing is the worst kind of
failure, because it is invisible. So there is no `Broker` protocol here, no
`PaperBroker`, and no `execute()` that might be wired to something real later. When live routing
is specified it will have to touch this function by name, which is exactly the review that
decision deserves.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import now_utc
from app.domain.position import (
    Book,
    FillSource,
    Position,
    Side,
    Trade,
    derive_position,
    empty_position,
)
from app.persistence.models import Trade as TradeRow

log = logging.getLogger(__name__)

#: Bound on the trade listing endpoint. This table sees a few hundred rows a year, but an
#: unbounded query is a habit worth not forming.
MAX_TRADES = 500


class InsufficientQuantity(ValueError):
    """Selling more than the book holds.

    Refused rather than clamped at the boundary: the ledger's own fold clamps defensively, but
    a caller asking to sell 100 of a 40-share holding has made a mistake worth hearing about
    rather than silently having it rounded down.
    """


class Ledger:
    """Trades in, positions out. The book is a parameter."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    # ── the execution boundary ────────────────────────────────────────────────
    def fill(
        self,
        book: Book,
        ticker: str,
        side: Side,
        quantity: int,
        price: float,
        *,
        executed_at: datetime | None = None,
        source: FillSource = FillSource.MANUAL,
        strategy_id: str | None = None,
        note: str | None = None,
    ) -> Trade:
        """Record a paper fill. The single place a trade comes into existence."""
        symbol = ticker.strip().upper()
        trade = Trade(
            book=book,
            ticker=symbol,
            side=side,
            quantity=quantity,
            price=price,
            executed_at=executed_at or now_utc(),
            source=source,
            strategy_id=strategy_id,
            note=note,
        )

        if side is Side.SELL:
            held = self.position(book, symbol).quantity
            if quantity > held:
                raise InsufficientQuantity(
                    f"cannot sell {quantity} of {symbol} in {book.value}: {held} held"
                )

        with self._sessions() as session:
            row = TradeRow(
                book=book.value,
                ticker=symbol,
                side=side.value,
                quantity=quantity,
                price=price,
                executed_at=trade.executed_at,
                source=source.value,
                strategy_id=strategy_id,
                note=note,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _to_trade(row)

    # ── reading ───────────────────────────────────────────────────────────────
    def trades(
        self, book: Book | None = None, ticker: str | None = None, limit: int = MAX_TRADES
    ) -> list[Trade]:
        with self._sessions() as session:
            stmt = select(TradeRow).order_by(TradeRow.executed_at.desc(), TradeRow.id.desc())
            if book is not None:
                stmt = stmt.where(TradeRow.book == book.value)
            if ticker:
                stmt = stmt.where(TradeRow.ticker == ticker.strip().upper())
            rows = session.execute(stmt.limit(limit)).scalars().all()
            return [_to_trade(row) for row in rows]

    def position(self, book: Book, ticker: str) -> Position:
        """Derived from this symbol's trades, never read from a stored figure."""
        symbol = ticker.strip().upper()
        with self._sessions() as session:
            rows = (
                session.execute(
                    select(TradeRow).where(
                        TradeRow.book == book.value, TradeRow.ticker == symbol
                    )
                )
                .scalars()
                .all()
            )
        if not rows:
            return empty_position(book, symbol)
        return derive_position(book, symbol, [_to_trade(r) for r in rows])

    def positions(self, book: Book, open_only: bool = True) -> list[Position]:
        """Every position in a book, derived from its trades.

        One pass over the book's trades grouped in Python rather than a query per symbol: the
        table is small, and N+1 queries to answer "what do I hold" is the wrong shape whatever
        the size.
        """
        with self._sessions() as session:
            rows = (
                session.execute(select(TradeRow).where(TradeRow.book == book.value))
                .scalars()
                .all()
            )

        by_ticker: dict[str, list[Trade]] = {}
        for row in rows:
            by_ticker.setdefault(row.ticker, []).append(_to_trade(row))

        found = [derive_position(book, ticker, trades) for ticker, trades in by_ticker.items()]
        if open_only:
            found = [p for p in found if p.is_open]
        return sorted(found, key=lambda p: p.ticker)

    def held_tickers(self, book: Book) -> set[str]:
        return {p.ticker for p in self.positions(book, open_only=True)}


def _to_trade(row: TradeRow) -> Trade:
    return Trade(
        id=row.id,
        book=Book(row.book),
        ticker=row.ticker,
        side=Side(row.side),
        quantity=row.quantity,
        price=row.price,
        executed_at=row.executed_at,
        source=FillSource(row.source),
        strategy_id=row.strategy_id,
        note=row.note,
    )

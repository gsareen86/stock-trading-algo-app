"""Positions, trades and portfolio analytics — per book.

`POST /books/{book}/fill` is the platform's one execution boundary reached over HTTP. It records
a **paper** fill and nothing else; there is no broker behind it, and principle 7 says there must
not be one that silently does nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.deps import get_session_factory, get_settings
from app.books import analytics as analytics_module
from app.books.ledger import MAX_TRADES, InsufficientQuantity, Ledger
from app.core.settings import Settings
from app.domain.instrument import Instrument
from app.domain.position import Book, FillSource, Side

router = APIRouter(prefix="/books", tags=["books"])


def _ledger(session_factory) -> Ledger:
    return Ledger(session_factory)


def _last_prices(request: Request, settings: Settings, tickers: list[str]) -> dict[str, float]:
    """Best-effort marks. A missing price leaves the position unvalued rather than valued at
    zero — see `Position.unrealised_pnl`."""
    from app.api.verdicts import _price_source

    source = _price_source(request, settings)
    prices: dict[str, float] = {}
    for ticker in tickers:
        try:
            series = source.history(Instrument(ticker), interval="1d", lookback_days=30)
        except Exception:  # pragma: no cover - sources are contracted not to raise
            continue
        if series.last_close is not None:
            prices[ticker] = series.last_close
    return prices


class FillRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    side: Side
    quantity: int = Field(gt=0)
    #: Gross of brokerage, STT, stamp duty and GST — the platform models no charges.
    price: float = Field(gt=0)
    executed_at: datetime | None = None
    strategy_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


@router.post("/{book}/fill")
async def fill(
    book: Book,
    payload: FillRequest,
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    ledger = _ledger(session_factory)
    try:
        trade = ledger.fill(
            book,
            payload.ticker,
            payload.side,
            payload.quantity,
            payload.price,
            executed_at=payload.executed_at,
            source=FillSource.MANUAL,
            strategy_id=payload.strategy_id,
            note=payload.note,
        )
    except InsufficientQuantity as exc:
        # A caller selling more than the book holds has made a mistake worth hearing about,
        # rather than silently having it rounded down to what is held.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "trade": trade.as_dict(),
        "position": ledger.position(book, payload.ticker).as_dict(),
    }


@router.get("/{book}/positions")
async def positions(
    book: Book,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    open_only: bool = True,
) -> dict[str, Any]:
    held = _ledger(session_factory).positions(book, open_only=open_only)
    prices = _last_prices(request, settings, [p.ticker for p in held])
    return {
        "book": book.value,
        "count": len(held),
        "positions": [p.as_dict(prices.get(p.ticker)) for p in held],
        "charges_included": False,
    }


@router.get("/{book}/trades")
async def trades(
    book: Book,
    session_factory: Annotated[Any, Depends(get_session_factory)],
    ticker: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_TRADES)] = 100,
) -> dict[str, Any]:
    found = _ledger(session_factory).trades(book, ticker=ticker, limit=limit)
    return {"book": book.value, "count": len(found), "trades": [t.as_dict() for t in found]}


@router.get("/{book}/analytics")
async def book_analytics(
    book: Book,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
) -> dict[str, Any]:
    ledger = _ledger(session_factory)
    all_positions = ledger.positions(book, open_only=False)
    book_trades = ledger.trades(book, limit=MAX_TRADES)
    prices = _last_prices(request, settings, [p.ticker for p in all_positions if p.is_open])

    report = analytics_module.build(book, all_positions, book_trades, prices).as_dict()
    report["closed_trades"] = analytics_module.closed_trade_stats(all_positions)
    # Activity per strategy — never a ranking. "Which strategy performed best" is a question
    # this platform deliberately cannot answer with one number.
    report["attribution"] = analytics_module.attribution(book_trades)
    return report

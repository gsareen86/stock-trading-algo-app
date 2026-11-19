"""Inspect open paper-book positions and tracked watchlist entries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from app.books.ledger import Ledger
from app.core.clock import now_utc
from app.domain.position import Book
from app.persistence.models import WatchlistItem
from app.tools.evidence import item_schema, items_output_schema
from app.tools.types import ToolContext, ToolManifest

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "book": {
            "type": "string",
            "enum": ["all", "swing", "longterm"],
            "default": "all",
        },
        "include_watchlist": {"type": "boolean", "default": True},
    },
    "additionalProperties": False,
}

ITEM_SCHEMA = item_schema(
    {
        "kind": {"type": "string", "enum": ["holding", "watchlist"]},
        "book": {"type": "string"},
        "symbol": {"type": "string"},
        "quantity": {"type": ["integer", "null"]},
        "average_cost": {"type": ["number", "null"]},
        "cost_basis": {"type": ["number", "null"]},
        "target_strategy_id": {"type": ["string", "null"]},
        "added_price": {"type": ["number", "null"]},
        "notes": {"type": ["string", "null"]},
    },
    required=["kind", "book", "symbol"],
)

OUTPUT_SCHEMA = items_output_schema(
    ITEM_SCHEMA,
    extra={
        "open_positions_count": {"type": "integer"},
        "watchlist_count": {"type": "integer"},
        "available": {"type": "boolean"},
    },
)


def handle(arguments: dict, context: ToolContext) -> dict:
    observed_at = (context.now() if context.now else now_utc()).isoformat()
    if context.session_factory is None:
        return {
            "open_positions_count": 0,
            "watchlist_count": 0,
            "available": False,
            "items": [],
        }

    book_filter = arguments.get("book", "all")
    include_watchlist = bool(arguments.get("include_watchlist", True))
    target_books = [Book.SWING, Book.LONGTERM] if book_filter == "all" else [Book(book_filter)]

    items: list[dict[str, Any]] = []
    open_count = 0
    ledger = Ledger(context.session_factory)
    for b in target_books:
        for pos in ledger.positions(b):
            if not pos.is_open:
                continue
            open_count += 1
            items.append(
                {
                    "source_ref": f"book://{b.value}/{pos.ticker}",
                    "observed_at": observed_at,
                    "kind": "holding",
                    "book": b.value,
                    "symbol": pos.ticker,
                    "quantity": pos.quantity,
                    "average_cost": round(pos.average_cost, 2),
                    "cost_basis": round(pos.cost_basis, 2),
                    "target_strategy_id": None,
                    "added_price": None,
                    "notes": None,
                }
            )

    watch_count = 0
    if include_watchlist:
        with context.session_factory() as session:
            stmt = select(WatchlistItem).order_by(desc(WatchlistItem.updated_at))
            if book_filter != "all":
                stmt = stmt.where(WatchlistItem.book_intent == book_filter)
            rows = session.execute(stmt).scalars().all()
        watch_count = len(rows)
        for row in rows:
            items.append(
                {
                    "source_ref": f"watchlist://{row.symbol}",
                    "observed_at": observed_at,
                    "kind": "watchlist",
                    "book": row.book_intent,
                    "symbol": row.symbol,
                    "quantity": None,
                    "average_cost": None,
                    "cost_basis": None,
                    "target_strategy_id": row.target_strategy_id,
                    "added_price": row.added_price,
                    "notes": row.notes,
                }
            )

    return {
        "open_positions_count": open_count,
        "watchlist_count": watch_count,
        "available": True,
        "items": items,
    }


TOOL = ToolManifest(
    name="portfolio_and_watchlist",
    version="1.0.0",
    summary=(
        "Reads open paper-book positions (swing and long-term) and user-tracked watchlist "
        "names. Use when prioritizing research or checking exposure against existing holdings."
    ),
    description=(
        "Lists open holdings derived from the trade ledger and user watchlist rows including "
        "book intent, target strategy, and personal thesis notes."
    ),
    input_schema=INPUT_SCHEMA,
    output_schema=OUTPUT_SCHEMA,
    handler=handle,
    tags=("books", "portfolio", "watchlist"),
)

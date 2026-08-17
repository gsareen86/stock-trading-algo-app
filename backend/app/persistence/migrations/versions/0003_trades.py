"""Add the trade ledger.

Revision ID: 0003_trades
Revises: 0002_llm_calls
Create Date: 2026-08-17

One table, not one per book: the book is a column. The predecessor kept three duplicate
position ledgers that drifted and could not be reconciled, which is design principle 2.

There is deliberately **no positions table**. A position is derived by folding a symbol's
trades, so a stored position can never disagree with the trades that produced it.

Same posture as 0001 and 0002: created in the ``trading`` schema, RLS enabled with a
``service_role`` policy in this same migration, nothing granted to ``anon`` or
``authenticated``. The predecessor's tables in ``public`` are not touched.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0003_trades"
down_revision: str | None = "0002_llm_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "book_trades"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("book", sa.String(length=16), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        # Gross of brokerage, STT, stamp duty and GST. Charges are deliberately unmodelled
        # rather than modelled badly — see the change's design notes.
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("strategy_id", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("book IN ('swing', 'longterm')", name="ck_book_trades_book"),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_book_trades_side"),
        # A zero-quantity row is not a trade and a negative one expresses the side twice;
        # either makes every derived position silently wrong.
        sa.CheckConstraint("quantity > 0", name="ck_book_trades_quantity"),
        sa.CheckConstraint("price > 0", name="ck_book_trades_price"),
        schema=schema,
    )
    op.create_index("ix_book_trades_book_ticker", TABLE, ["book", "ticker"], schema=schema)
    op.create_index("ix_book_trades_executed_at", TABLE, ["executed_at"], schema=schema)

    if _is_postgres():
        op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {TABLE}_service_role_all ON {SCHEMA}.{TABLE} "
            "FOR ALL TO service_role USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    schema = _schema()
    op.drop_index("ix_book_trades_executed_at", table_name=TABLE, schema=schema)
    op.drop_index("ix_book_trades_book_ticker", table_name=TABLE, schema=schema)
    op.drop_table(TABLE, schema=schema)

"""Add discovery scan runs, scan entries, and watchlist items tables.

Revision ID: 0011_discovery_and_watchlist
Revises: 0010_tier_research
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0011_discovery_and_watchlist"
down_revision: str | None = "0010_tier_research"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("scan_runs", "scan_entries", "watchlist_items")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="requested"),
        sa.Column("universe_origin", sa.String(length=16), nullable=False, server_default="live"),
        sa.Column(
            "index_name",
            sa.String(length=32),
            nullable=False,
            server_default="NIFTY_TOTAL_MARKET",
        ),
        sa.Column("benchmark", sa.String(length=16), nullable=False, server_default="^CRSLDX"),
        sa.Column("outcome", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("considered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligible_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unevaluable", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sectors_snapshot", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.create_index("ix_scan_runs_started", "scan_runs", ["started_at"], schema=schema)
    op.create_index("ix_scan_runs_outcome", "scan_runs", ["outcome"], schema=schema)

    op.create_table(
        "scan_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("universe_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("sector_key", sa.String(length=64), nullable=True),
        sa.Column("ranked_by", sa.String(length=64), nullable=False),
        sa.Column("ranked_conviction", sa.Integer(), nullable=False),
        sa.Column("ranked_stance", sa.String(length=8), nullable=False),
        sa.Column("buy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verdicts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("quality", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("themes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index("ix_scan_entries_run_id", "scan_entries", ["run_id"], schema=schema)
    op.create_index(
        "ix_scan_entries_run_conviction",
        "scan_entries",
        ["run_id", "ranked_conviction"],
        schema=schema,
    )
    op.create_index(
        "ix_scan_entries_run_symbol",
        "scan_entries",
        ["run_id", "symbol"],
        unique=True,
        schema=schema,
    )

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("book_intent", sa.String(length=16), nullable=False, server_default="swing"),
        sa.Column("target_strategy_id", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("added_price", sa.Float(), nullable=True),
        sa.Column("last_known_stances", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_watchlist_items_symbol", "watchlist_items", ["symbol"], unique=True, schema=schema
    )
    op.create_index("ix_watchlist_items_intent", "watchlist_items", ["book_intent"], schema=schema)

    if _is_postgres():
        for table in TABLES:
            op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_service_role ON {SCHEMA}.{table} "
                f"FOR ALL TO service_role USING (true) WITH CHECK (true)"
            )


def downgrade() -> None:
    schema = _schema()
    for table in reversed(TABLES):
        op.drop_table(table, schema=schema)

"""Create the rebuilt schema in its own namespace.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-15

The predecessor's 30 tables stay exactly where they are. They were believed empty when this
change was proposed; an exact row count showed ~47,500 rows, including 472 trades, 206
positions and 325 signal outcomes that later increments will want for backtesting. So the
rebuild takes its own ``trading`` schema rather than clearing ``public``.

Nothing in this migration is destructive. It creates a schema, two tables and their policies.

SQLite has no schemas, so the namespace collapses to ``None`` there — one set of models,
both dialects.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tables this migration creates. Each gets RLS enabled *and* a policy, in this same
#: migration — a bare ENABLE with no policy would lock the application out.
NEW_TABLES: tuple[str, ...] = ("verdicts", "insights")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    """The namespace to create in — ``None`` on SQLite, which has no schemas."""
    return SCHEMA if _is_postgres() else None


def _create_namespace() -> None:
    """Create the schema and grant it to the server-side role only.

    ``anon`` and ``authenticated`` are deliberately granted nothing. The browser is not a
    database client here; it reaches data through the API. As a side benefit, PostgREST only
    exposes schemas it is configured for, so a non-``public`` schema is not reachable over the
    REST API at all unless someone opts it in.
    """
    if not _is_postgres():
        return
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO service_role")
    op.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA {SCHEMA} TO service_role")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT ALL ON TABLES TO service_role")


def _enable_rls() -> None:
    """Enable RLS and create the service-role policy for each new table.

    No policy is created for ``anon`` or ``authenticated``: under Postgres RLS the absence of
    a permissive policy is a deny. The ``service_role`` policy is technically redundant (that
    role bypasses RLS) but records the intended access in the schema itself, so "RLS on, zero
    policies" never has to be read as an oversight.
    """
    if not _is_postgres():
        return
    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_service_role_all ON {SCHEMA}.{table} "
            "FOR ALL TO service_role USING (true) WITH CHECK (true)"
        )


def upgrade() -> None:
    _create_namespace()
    schema = _schema()

    op.create_table(
        "verdicts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stance", sa.String(length=8), nullable=False),
        sa.Column("conviction", sa.Integer(), nullable=False),
        sa.Column("gates", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("stance IN ('BUY', 'WATCH', 'AVOID')", name="ck_verdicts_stance"),
        sa.CheckConstraint(
            "conviction >= 0 AND conviction <= 100", name="ck_verdicts_conviction_range"
        ),
        schema=schema,
    )
    op.create_index("ix_verdicts_ticker_as_of", "verdicts", ["ticker", "as_of"], schema=schema)
    op.create_index(
        "ix_verdicts_strategy_as_of", "verdicts", ["strategy_id", "as_of"], schema=schema
    )

    op.create_table(
        "insights",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=schema,
    )
    op.create_index("ix_insights_created_at", "insights", ["created_at"], schema=schema)
    op.create_index("ix_insights_ticker", "insights", ["ticker"], schema=schema)

    _enable_rls()


def downgrade() -> None:
    schema = _schema()

    op.drop_index("ix_insights_ticker", table_name="insights", schema=schema)
    op.drop_index("ix_insights_created_at", table_name="insights", schema=schema)
    op.drop_table("insights", schema=schema)

    op.drop_index("ix_verdicts_strategy_as_of", table_name="verdicts", schema=schema)
    op.drop_index("ix_verdicts_ticker_as_of", table_name="verdicts", schema=schema)
    op.drop_table("verdicts", schema=schema)

    # The schema itself is left in place: dropping it would also remove anything a later
    # increment created there, and an empty schema costs nothing.

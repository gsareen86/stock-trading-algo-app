"""Drop the legacy schema and create the rebuilt one.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-15

This is the one irreversible step in the bootstrap change, so it carries two guards:

* the drop list is **explicit and hard-coded** — never ``DROP SCHEMA`` and never a
  reflection-driven loop, so a table that is not on the list is never touched;
* every listed table is **asserted empty before anything is dropped**, and the whole
  transaction aborts otherwise.

All 30 legacy tables were verified at 0 rows when this was written. The assertion exists for
the case where that stops being true before it runs.

``downgrade()`` deliberately does not recreate the legacy tables — they hold nothing worth
reconstructing, and fabricating 30 empty tables would imply a rollback path that does not
really exist.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.legacy import assert_all_empty

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tables this migration creates. Each gets RLS enabled *and* a policy, in this same
#: migration — a bare ENABLE with no policy would lock the application out.
NEW_TABLES: tuple[str, ...] = ("verdicts", "insights")


def _drop_legacy_tables() -> None:
    """Verify every legacy table is empty, then drop them.

    ``assert_all_empty`` raises before anything is dropped if any table holds rows, so an
    abort leaves the schema exactly as it was.
    """
    for table in assert_all_empty(op.get_bind()):
        op.drop_table(table)


def _enable_rls() -> None:
    """Enable RLS and create the service-role policy for each new table.

    No policy is created for ``anon`` or ``authenticated``: under Postgres RLS the absence of
    a permissive policy is a deny, and the browser is not a database client here — it reaches
    data through the API, which holds the service-role credential server-side.

    The ``service_role`` policy is technically redundant (that role bypasses RLS) but records
    the intended access in the schema itself.
    """
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite has no RLS

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_service_role_all ON public.{table} "
            "FOR ALL TO service_role USING (true) WITH CHECK (true)"
        )


def upgrade() -> None:
    _drop_legacy_tables()

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
    )
    op.create_index("ix_verdicts_ticker_as_of", "verdicts", ["ticker", "as_of"])
    op.create_index("ix_verdicts_strategy_as_of", "verdicts", ["strategy_id", "as_of"])

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
    )
    op.create_index("ix_insights_created_at", "insights", ["created_at"])
    op.create_index("ix_insights_ticker", "insights", ["ticker"])

    _enable_rls()


def downgrade() -> None:
    op.drop_index("ix_insights_ticker", table_name="insights")
    op.drop_index("ix_insights_created_at", table_name="insights")
    op.drop_table("insights")

    op.drop_index("ix_verdicts_strategy_as_of", table_name="verdicts")
    op.drop_index("ix_verdicts_ticker_as_of", table_name="verdicts")
    op.drop_table("verdicts")

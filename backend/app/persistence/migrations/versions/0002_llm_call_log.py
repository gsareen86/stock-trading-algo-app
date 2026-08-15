"""Add the LLM call log.

Revision ID: 0002_llm_calls
Revises: 0001_initial
Create Date: 2026-08-15

One row per call attempt, recorded regardless of outcome, so cost and failure modes are
answerable without an external observability service.

Same posture as 0001: created in the ``trading`` schema, RLS enabled with a ``service_role``
policy in this same migration, nothing granted to ``anon`` or ``authenticated``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0002_llm_calls"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "llm_calls"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("requested_model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("used_fallback", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rung_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        # Nullable: local providers report no cost, and 0.0 would overstate confidence.
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("error_msg", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'cached', 'failed', 'rate_limited', "
            "'breaker_open', 'budget_exceeded')",
            name="ck_llm_calls_status",
        ),
        schema=schema,
    )
    op.create_index("ix_llm_calls_created_at", TABLE, ["created_at"], schema=schema)
    op.create_index("ix_llm_calls_task_created", TABLE, ["task", "created_at"], schema=schema)

    if _is_postgres():
        op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {TABLE}_service_role_all ON {SCHEMA}.{TABLE} "
            "FOR ALL TO service_role USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    schema = _schema()
    op.drop_index("ix_llm_calls_task_created", table_name=TABLE, schema=schema)
    op.drop_index("ix_llm_calls_created_at", table_name=TABLE, schema=schema)
    op.drop_table(TABLE, schema=schema)

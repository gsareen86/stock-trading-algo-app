"""Count requests spent against a metered data provider.

Revision ID: 0007_provider_requests
Revises: 0006_insight_lifecycle
Create Date: 2026-08-20

The financials provider allows 500 requests a *month* on its free tier — roughly sixteen a
day. That is enough for the platform's actual reading pattern and nowhere near enough to
survive one careless full-universe scan, so the allowance has to be enforced rather than
hoped for.

A row per request rather than a counter. A count is derivable from rows; rows are not
derivable from a count, and the only question worth asking when an allowance runs out early
is *which calls did that*.

Rows are written before the call, not after: a request that was made and then failed still
consumed the allowance, and a counter that recorded only successes would drift under exactly
the conditions that make the cap matter.

Same posture as every migration before it: `trading` schema on Postgres, translated away on
SQLite, nothing granted to `anon` or `authenticated`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0007_provider_requests"
down_revision: str | None = "0006_insight_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "provider_requests"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        # What the request was for, so an exhausted allowance can be explained. Never a
        # credential — the same rule the health endpoint follows.
        sa.Column("detail", sa.String(length=200), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    # The only question asked of this table: how many, for this provider, since a moment.
    op.create_index(
        "ix_provider_requests_provider_at", TABLE, ["provider", "requested_at"], schema=schema
    )

    if _is_postgres():
        # RLS enabled *with* a policy in the same migration — a bare ENABLE locks the app out.
        op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {TABLE}_service_role ON {SCHEMA}.{TABLE} "
            f"FOR ALL TO service_role USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    schema = _schema()
    op.drop_index("ix_provider_requests_provider_at", table_name=TABLE, schema=schema)
    op.drop_table(TABLE, schema=schema)

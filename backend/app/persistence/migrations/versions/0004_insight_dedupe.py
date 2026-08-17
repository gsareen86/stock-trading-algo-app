"""Give insights a dedupe key and a declared severity.

Revision ID: 0004_insight_dedupe
Revises: 0003_trades
Create Date: 2026-08-17

The ``insights`` table has existed since 0001 with no writer. `insights-feed` is the first
change to populate it, and two columns are needed before it can.

``dedupe_key`` is what keeps a daily cycle from raising the same observation every morning
until the feed is something to scroll past. ``severity`` belongs to the insight *kind* and is
stored rather than computed, so it can never become a per-item score compared across kinds —
which would be a ranking, which is the scorecard this rebuild removed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0004_insight_dedupe"
down_revision: str | None = "0003_trades"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "insights"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def upgrade() -> None:
    schema = _schema()

    op.add_column(
        TABLE,
        sa.Column("dedupe_key", sa.String(length=200), nullable=False, server_default=""),
        schema=schema,
    )
    op.add_column(
        TABLE,
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        schema=schema,
    )
    # Suppression asks "was this key raised since T", which is this index exactly.
    op.create_index(
        "ix_insights_dedupe_created", TABLE, ["dedupe_key", "created_at"], schema=schema
    )
    op.create_index("ix_insights_severity", TABLE, ["severity"], schema=schema)


def downgrade() -> None:
    schema = _schema()
    op.drop_index("ix_insights_severity", table_name=TABLE, schema=schema)
    op.drop_index("ix_insights_dedupe_created", table_name=TABLE, schema=schema)
    op.drop_column(TABLE, "severity", schema=schema)
    op.drop_column(TABLE, "dedupe_key", schema=schema)

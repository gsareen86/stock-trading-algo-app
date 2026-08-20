"""Give an insight a lifecycle: when it was last measured, and when it stopped being true.

Revision ID: 0006_insight_lifecycle
Revises: 0005_auth
Create Date: 2026-08-19

`0004` added suppression, which answers "is this the same observation as one already standing".
It never asked the two questions either side of it — is it still true, and is the figure it
carries still the figure. So the first row ever written for a dedupe key was the row that stood
forever: a concentration insight kept reporting 35.1% of a book whose position had been closed
to zero, and a regime insight kept reporting a benchmark level three days stale.

`measured_at` separates *when we first said this* from *when we last checked it*, which is what
lets a figure be refreshed without the observation looking new every morning.

`withdrawn_at` is how an observation ends. It is not a delete: "this was true for eleven days
and then stopped" is exactly the history the feed exists to carry, and a row that vanishes
carries none of it.

Same posture as every migration before it: `trading` schema on Postgres, translated away on
SQLite, nothing granted to `anon` or `authenticated`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0006_insight_lifecycle"
down_revision: str | None = "0005_auth"
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
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.add_column(
        TABLE,
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.add_column(
        TABLE,
        sa.Column("withdrawal_reason", sa.Text(), nullable=True),
        schema=schema,
    )

    qualified = f"{schema}.{TABLE}" if schema else TABLE

    # Existing rows were measured when they were raised — that is the only honest backfill,
    # and leaving it null would make every pre-existing figure look unverifiable rather than
    # simply old.
    op.execute(f"UPDATE {qualified} SET measured_at = created_at WHERE measured_at IS NULL")

    # The default feed is "everything not withdrawn, newest first". Without this the query
    # degrades to a full scan the moment withdrawals outnumber standing insights, which is the
    # steady state for a feed that has been running a while.
    op.create_index(
        "ix_insights_withdrawn_created", TABLE, ["withdrawn_at", "created_at"], schema=schema
    )

    # ── the dedupe keys the same change unbanded ──────────────────────────────
    # `concentration:RELIANCE:35` and `book_full:8` carried a *band* of the measurement in the
    # key, so a position drifting across a boundary minted a new insight. That was a
    # workaround for having no way to update a standing row; reconciliation replaces it.
    #
    # Rewriting the existing rows is not optional. Leaving them means every banded row fails
    # to match its own unbanded candidate on the next cycle — so it is withdrawn as though the
    # observation ended, and immediately re-raised as a new one that has lost its age and its
    # read state. Observed on real data: a live TCS concentration insight retired with the
    # reason "no longer above the cap" while it was still 100% of the book.
    op.execute(
        f"""
        UPDATE {qualified}
           SET dedupe_key = 'concentration:' || ticker
         WHERE dedupe_key LIKE 'concentration:%:%'
        """
    )
    op.execute(
        f"""
        UPDATE {qualified}
           SET dedupe_key = 'book_full'
         WHERE dedupe_key LIKE 'book\\_full:%' ESCAPE '\\'
        """
    )


def downgrade() -> None:
    schema = _schema()
    op.drop_index("ix_insights_withdrawn_created", table_name=TABLE, schema=schema)
    op.drop_column(TABLE, "withdrawal_reason", schema=schema)
    op.drop_column(TABLE, "withdrawn_at", schema=schema)
    op.drop_column(TABLE, "measured_at", schema=schema)

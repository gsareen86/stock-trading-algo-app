"""Themes, the chains they imply, and the candidates those resolve to.

Revision ID: 0008_themes
Revises: 0007_provider_requests
Create Date: 2026-08-21

Five tables, and the shape of them encodes the change's central distinction: a **theme** is
counted and a **chain link** is proposed. The first stores measurements — breadth, persistence,
sector count — and the second stores a model's reasoning alongside the model that gave it and a
rejection that survives later runs.

`theme_runs.sources_unavailable` is the column that stops a quiet failure looking like a quiet
market. Commentary is scrape-only and fails often; a run that surfaced three themes because the
documents would not download has to be distinguishable from one that genuinely found three.

`themes` carries the lifecycle `insights` gained in `0006`, for the same reason and with the
same rule: withdrawal is not deletion, and `first_seen_at` is never reset, so "emerging since
March" survives a theme's counts moving.

Same posture as every migration before it: `trading` schema on Postgres, translated away on
SQLite, RLS enabled with a policy in this same migration, nothing granted to `anon` or
`authenticated`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0008_themes"
down_revision: str | None = "0007_provider_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("theme_runs", "themes", "theme_references", "chain_links", "theme_candidates")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def _timestamp(name: str, *, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=not default,
        server_default=sa.func.now() if default else None,
    )


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "theme_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="requested"),
        sa.Column("outcome", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("sources_unavailable", sa.JSON(), nullable=False),
        sa.Column("documents_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=True),
        _timestamp("started_at", default=True),
        _timestamp("finished_at"),
        schema=schema,
    )
    op.create_index("ix_theme_runs_started", "theme_runs", ["started_at"], schema=schema)

    op.create_table(
        "themes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        # Stored rather than recomputed on read: the counts *are* the claim being made, so
        # they must be the figures the run measured, not ones re-derived later from a
        # different set of rows.
        sa.Column("breadth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("persistence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sector_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_kinds", sa.JSON(), nullable=False),
        _timestamp("first_seen_at", default=True),
        _timestamp("measured_at"),
        _timestamp("withdrawn_at"),
        sa.Column("withdrawal_reason", sa.Text(), nullable=True),
        schema=schema,
    )
    op.create_index("ix_themes_key", "themes", ["key"], unique=True, schema=schema)
    op.create_index("ix_themes_withdrawn", "themes", ["withdrawn_at"], schema=schema)

    op.create_table(
        "theme_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("theme_key", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=False),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        _timestamp("observed_at", default=True),
        schema=schema,
    )
    op.create_index(
        "ix_theme_references_theme", "theme_references", ["theme_key"], schema=schema
    )
    # The same company saying the same thing in the same period twice is one reference —
    # otherwise re-reading a document would inflate breadth.
    op.create_index(
        "ix_theme_references_unique",
        "theme_references",
        ["theme_key", "symbol", "period", "source_ref"],
        unique=True,
        schema=schema,
    )

    op.create_table(
        "chain_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("theme_key", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("supplies", sa.String(length=200), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        # Attribution, so a link never reads as a measurement the platform made.
        sa.Column("proposed_by", sa.String(length=128), nullable=False),
        sa.Column("supplier_descriptions", sa.JSON(), nullable=False),
        # Survives later runs. Without that, every run re-proposes the same wrong link and the
        # reader re-rejects it forever.
        _timestamp("rejected_at"),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        _timestamp("created_at", default=True),
        schema=schema,
    )
    op.create_index(
        "ix_chain_links_theme_tier", "chain_links", ["theme_key", "tier"], schema=schema
    )
    op.create_index(
        "ix_chain_links_identity",
        "chain_links",
        ["theme_key", "tier", "label"],
        unique=True,
        schema=schema,
    )

    op.create_table(
        "theme_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("theme_key", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        # A named grade, never a number. A number would be sortable, and sorting candidates by
        # theme exposure is a ranking this platform does not permit.
        sa.Column("exposure", sa.String(length=16), nullable=False),
        sa.Column("exposure_basis", sa.Text(), nullable=True),
        sa.Column("matched_description", sa.String(length=200), nullable=True),
        _timestamp("created_at", default=True),
        schema=schema,
    )
    op.create_index(
        "ix_theme_candidates_theme", "theme_candidates", ["theme_key"], schema=schema
    )
    op.create_index(
        "ix_theme_candidates_identity",
        "theme_candidates",
        ["theme_key", "tier", "symbol"],
        unique=True,
        schema=schema,
    )

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

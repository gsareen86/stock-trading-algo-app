"""Store what a tier decomposed into, and every company search proposed.

Revision ID: 0010_tier_research
Revises: 0009_document_concepts
Create Date: 2026-08-21

Two tables for the two halves of tier research, and they are separate because they carry
different risk and are read for different reasons.

`chain_sub_categories` holds what a coarse tier breaks into. A tier arrives at the granularity
a model volunteers -- "semiconductor fabrication" -- which is coarser than the market, and a
coarse tier is imprecise in both directions at once: it matched CG Power on the single word
`semiconductor`, tied with Infosys, Shree Cement and Voltas. Decomposed into outsourced
assembly and test, the same company matches on four words and ranks first. The sub-category is
also where a *precise negative* can live: EUV lithography has no Indian listed expression, and
that is a finding worth as much as a name, but only if it can be recorded against the thing it
is true of.

`theme_proposals` holds every company a search proposed, **including the ones the platform
refused**. That is the point of the table rather than a detail of it. A proposal that matched
nothing is kept as *proposed but not found*, and an ambiguous one as *ambiguous*, so the record
shows what was suggested and what the platform declined to act on. Storing only the successes
would leave no evidence that the refusals ever happened, and the refusals are the safety
property.

`searched_at` and `search_outcome` on a sub-category exist so "searched and found nothing" and
"never searched" can be told apart. They look the same on a screen and mean opposite things.

Same posture as every migration before it: `trading` schema on Postgres, translated away on
SQLite, RLS enabled with a policy in this same migration, nothing granted to `anon` or
`authenticated`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0010_tier_research"
down_revision: str | None = "0009_document_concepts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("chain_sub_categories", "theme_proposals")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "chain_sub_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("theme_key", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        # The coarse tier this came out of, so a sub-category can be shown under its parent.
        sa.Column("tier_label", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        # What resolution matches against. The label is what a reader sees.
        sa.Column("supplier_descriptions", sa.JSON(), nullable=False, server_default="[]"),
        # Recognisable names, frequently listed abroad. Explanation only, never candidates.
        sa.Column("notable_examples", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("proposed_by", sa.String(length=128), nullable=False, server_default=""),
        # Null means never searched, which is not the same as searched and empty.
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=True),
        # `ok`, `unconfigured`, `exhausted` or `unavailable`.
        sa.Column("search_outcome", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_chain_sub_categories_theme",
        "chain_sub_categories",
        ["theme_key", "tier"],
        schema=schema,
    )
    # One sub-category per label per tier. A weekly run re-proposes the same breakdown, and
    # duplicates would multiply a tier's apparent breadth without anything new being found.
    op.create_index(
        "ix_chain_sub_categories_identity",
        "chain_sub_categories",
        ["theme_key", "tier", "label"],
        unique=True,
        schema=schema,
    )

    op.create_table(
        "theme_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("theme_key", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("sub_category", sa.String(length=200), nullable=False),
        # The name as proposed, kept verbatim even when it resolved to nothing.
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        # At least one followable URL. A proposal without one never reaches this table.
        sa.Column("sources", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("proposed_by", sa.String(length=128), nullable=False, server_default=""),
        # `resolved`, `not_found` or `ambiguous`. Only the first can become a candidate.
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("matched_name", sa.String(length=200), nullable=True),
        # Every instrument an ambiguous name touched, so the confusion is legible.
        sa.Column("matched", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_theme_proposals_theme", "theme_proposals", ["theme_key", "tier"], schema=schema
    )
    op.create_index(
        "ix_theme_proposals_identity",
        "theme_proposals",
        ["theme_key", "tier", "sub_category", "company"],
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

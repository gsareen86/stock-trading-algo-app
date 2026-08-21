"""Store what a model read out of a document, and where each concept was placed.

Revision ID: 0009_document_concepts
Revises: 0008_themes
Create Date: 2026-08-21

Theme detection used to match ten hardcoded phrase groups, which could only ever find themes
somebody had already typed in. A model reads documents instead — but a model answers
differently each time it is asked, and breadth and persistence are only meaningful if the same
corpus yields the same numbers.

These two tables are how both hold at once. Extraction is written down, so counting is
arithmetic over stored rows and re-reading a document becomes deliberate rather than
accidental. Placement is stored *separately* from extraction because the two change for
different reasons: a document is read once, while a merge may be revised as more themes stand,
or rejected by a reader who disagrees.

Splitting them also means a re-merge never costs a re-read, which matters when reading is a
slow local model call and merging is a cheap one.

Same posture as every migration before it: `trading` schema on Postgres, translated away on
SQLite, RLS enabled with a policy in this same migration, nothing granted to `anon` or
`authenticated`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0009_document_concepts"
down_revision: str | None = "0008_themes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("document_concepts", "concept_placements")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "document_concepts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        # In the company's own words. Not a theme until it is placed.
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="commentary"),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("source_ref", sa.String(length=500), nullable=False),
        sa.Column("extracted_by", sa.String(length=128), nullable=False, server_default=""),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index("ix_document_concepts_label", "document_concepts", ["label"], schema=schema)
    op.create_index(
        "ix_document_concepts_symbol_period",
        "document_concepts",
        ["symbol", "period"],
        schema=schema,
    )
    # Re-reading a document must not double that company's contribution to breadth.
    op.create_index(
        "ix_document_concepts_identity",
        "document_concepts",
        ["source_ref", "label"],
        unique=True,
        schema=schema,
    )

    op.create_table(
        "concept_placements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("theme_key", sa.String(length=200), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=False, server_default=""),
        # Survives later runs. Re-proposing a merge somebody threw out is how a review surface
        # becomes one people stop reading.
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_concept_placements_label", "concept_placements", ["label"], unique=True, schema=schema
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

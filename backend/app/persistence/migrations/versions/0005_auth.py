"""Add users and revocable refresh tokens.

Revision ID: 0005_auth
Revises: 0004_insight_dedupe
Create Date: 2026-08-17

Until now every endpoint was open, including the ones that write trades and spend an LLM
budget. These two tables are what a login needs.

`refresh_tokens` stores a token's *identifier*, never the token: a leaked copy of this table
must not let anyone reconstruct a usable credential. It exists so that logging out revokes
rather than merely forgets — a JWT cannot be un-issued.

Same posture as every migration before it: created in the ``trading`` schema, RLS enabled with
a ``service_role`` policy in this same migration, nothing granted to ``anon`` or
``authenticated``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.persistence.base import SCHEMA

revision: str = "0005_auth"
down_revision: str | None = "0004_insight_dedupe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USERS = "users"
TOKENS = "refresh_tokens"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _schema() -> str | None:
    return SCHEMA if _is_postgres() else None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        USERS,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        # Argon2id. The only representation of a password that exists anywhere in this system.
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=schema,
    )
    op.create_index("ix_users_username", USERS, ["username"], unique=True, schema=schema)

    op.create_table(
        TOKENS,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=schema,
    )
    op.create_index("ix_refresh_tokens_jti", TOKENS, ["jti"], unique=True, schema=schema)
    op.create_index("ix_refresh_tokens_user", TOKENS, ["user_id"], schema=schema)

    if _is_postgres():
        for table in (USERS, TOKENS):
            op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_service_role_all ON {SCHEMA}.{table} "
                "FOR ALL TO service_role USING (true) WITH CHECK (true)"
            )


def downgrade() -> None:
    schema = _schema()
    op.drop_index("ix_refresh_tokens_user", table_name=TOKENS, schema=schema)
    op.drop_index("ix_refresh_tokens_jti", table_name=TOKENS, schema=schema)
    op.drop_table(TOKENS, schema=schema)
    op.drop_index("ix_users_username", table_name=USERS, schema=schema)
    op.drop_table(USERS, schema=schema)

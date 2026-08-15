"""Alembic environment.

The database URL comes from ``Settings``, not from ``alembic.ini`` — one precedence chain for
every setting, migrations included.

The platform owns the ``trading`` schema on Postgres. On SQLite that namespace is translated
away, and Alembic's own version table follows the same rule, so ``alembic_version`` lives
beside the tables it describes rather than in ``public``.
"""

from __future__ import annotations

from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.settings import Settings
from app.persistence import models  # noqa: F401  (import registers the tables on Base)
from app.persistence.base import SCHEMA, SQLITE_SCHEMA_TRANSLATE, Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_settings = Settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)

_IS_SQLITE = _settings.is_sqlite
#: SQLite has no schemas, so both the tables and the version table collapse to the default.
_VERSION_TABLE_SCHEMA = None if _IS_SQLITE else SCHEMA
_SCHEMA_TRANSLATE = SQLITE_SCHEMA_TRANSLATE if _IS_SQLITE else {}


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection (``alembic upgrade head --sql``).

    This is how the Supabase schema is applied: the same revision that runs against SQLite
    renders the exact SQL applied to Postgres, so there is no second source of truth.
    """
    if not _IS_SQLITE:
        # Alembic emits its version table before the first revision runs, and that table
        # lives in this schema — so the schema has to exist before Alembic touches anything.
        print(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA};\n")

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_schemas=True,
        version_table_schema=_VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if _SCHEMA_TRANSLATE:
            connection = connection.execution_options(schema_translate_map=_SCHEMA_TRANSLATE)
        else:
            # Same reason as the offline path: Alembic's version table lives in this schema,
            # and it creates that table before running the first revision.
            connection.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
            connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_schemas=True,
            version_table_schema=_VERSION_TABLE_SCHEMA,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

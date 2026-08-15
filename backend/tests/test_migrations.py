"""Schema migration and namespacing.

The rebuild lives in its own ``trading`` schema. The predecessor's 30 tables hold ~47,500 rows
of real history and are not touched — these tests are what stop that from silently changing.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.persistence.legacy import LEGACY_TABLES, assert_all_empty, present_legacy_tables
from tests.conftest import alembic_config


@contextmanager
def _database_url(url: str) -> Iterator[None]:
    """env.py builds its own Settings; point it at this database."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _upgrade(url: str) -> None:
    with _database_url(url):
        command.upgrade(alembic_config(url), "head")


def _tables(url: str) -> set[str]:
    return set(inspect(create_engine(url)).get_table_names())


class TestCleanDatabase:
    def test_upgrade_creates_expected_schema(self, sqlite_url: str) -> None:
        _upgrade(sqlite_url)

        assert {"verdicts", "insights", "alembic_version"} <= _tables(sqlite_url)

    def test_records_head_revision(self, migrated_url: str) -> None:
        with create_engine(migrated_url).connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

        assert revision == "0001_initial"

    def test_verdict_indexes_created(self, migrated_url: str) -> None:
        indexes = {
            index["name"] for index in inspect(create_engine(migrated_url)).get_indexes("verdicts")
        }

        assert {"ix_verdicts_ticker_as_of", "ix_verdicts_strategy_as_of"} <= indexes

    def test_migration_is_not_destructive(self, sqlite_url: str) -> None:
        """Nothing pre-existing is dropped — the migration only adds."""
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE anything_at_all (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO anything_at_all (id) VALUES (1)"))

        _upgrade(sqlite_url)

        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM anything_at_all")).scalar_one() == 1


class TestLegacyTablesAreLeftAlone:
    def test_populated_legacy_tables_survive_the_migration(self, sqlite_url: str) -> None:
        """The predecessor's data is the reason the rebuild is namespaced rather than a wipe."""
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            for name in ("trades", "positions", "signal_outcomes"):
                conn.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)"))
                conn.execute(text(f"INSERT INTO {name} (id) VALUES (1)"))

        _upgrade(sqlite_url)

        tables = _tables(sqlite_url)
        assert {"trades", "positions", "signal_outcomes"} <= tables
        assert {"verdicts", "insights"} <= tables
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM trades")).scalar_one() == 1

    def test_new_tables_do_not_collide_with_legacy_names(self) -> None:
        assert not ({"verdicts", "insights"} & set(LEGACY_TABLES))

    def test_inventory_covers_the_thirty_known_tables(self) -> None:
        assert len(LEGACY_TABLES) == 30
        assert len(set(LEGACY_TABLES)) == 30


class TestCleanupGuard:
    """The guard for the future milestone that retires the legacy tables.

    Not wired into any migration today — tested now, while there is no pressure on it, rather
    than written in a hurry on the day someone decides to delete 47,500 rows.
    """

    def test_reports_only_tables_that_exist(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE trades (id INTEGER PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)"))

        with engine.connect() as conn:
            assert present_legacy_tables(conn) == ["trades"]

    def test_passes_when_every_legacy_table_is_empty(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            for name in ("signals", "trades"):
                conn.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)"))

        with engine.connect() as conn:
            assert sorted(assert_all_empty(conn)) == ["signals", "trades"]

    def test_raises_naming_every_offending_table_with_row_counts(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            for name in ("news", "positions"):
                conn.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)"))
                conn.execute(text(f"INSERT INTO {name} (id) VALUES (1)"))

        with engine.connect() as conn, pytest.raises(RuntimeError) as excinfo:
            assert_all_empty(conn)

        message = str(excinfo.value)
        assert "news" in message and "positions" in message
        assert "1 rows" in message

    def test_ignores_tables_outside_the_inventory(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE my_scratch_notes (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO my_scratch_notes (id) VALUES (7)"))

        with engine.connect() as conn:
            assert assert_all_empty(conn) == []  # no error: not a legacy table


class TestDowngrade:
    def test_downgrade_removes_new_tables(self, migrated_url: str) -> None:
        with _database_url(migrated_url):
            command.downgrade(alembic_config(migrated_url), "base")

        assert not (_tables(migrated_url) & {"verdicts", "insights"})

    def test_downgrade_leaves_legacy_tables_alone(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE trades (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO trades (id) VALUES (1)"))
        _upgrade(sqlite_url)

        with _database_url(sqlite_url):
            command.downgrade(alembic_config(sqlite_url), "base")

        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM trades")).scalar_one() == 1


class TestDialectPortability:
    def test_schema_and_rls_statements_are_skipped_on_sqlite(self, sqlite_url: str) -> None:
        """SQLite has neither schemas nor RLS; the migration must still complete."""
        _upgrade(sqlite_url)

        assert {"verdicts", "insights"} <= _tables(sqlite_url)

    def test_models_declare_the_trading_namespace(self) -> None:
        from app.persistence.base import SCHEMA
        from app.persistence.models import Insight, Verdict

        assert Verdict.__table__.schema == SCHEMA
        assert Insight.__table__.schema == SCHEMA

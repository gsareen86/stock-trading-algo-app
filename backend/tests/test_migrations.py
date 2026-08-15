"""Schema migration, including the destructive legacy drop.

The drop is the one irreversible step in the bootstrap change. Its guards are asserted here
rather than trusted, because by the time they fail in production the data is already gone.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.persistence.legacy import LEGACY_TABLES
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

        tables = _tables(sqlite_url)
        assert {"verdicts", "insights", "alembic_version"} <= tables

    def test_records_head_revision(self, migrated_url: str) -> None:
        engine = create_engine(migrated_url)
        with engine.connect() as conn:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

        assert revision == "0001_initial"

    def test_verdict_indexes_created(self, migrated_url: str) -> None:
        indexes = {
            index["name"] for index in inspect(create_engine(migrated_url)).get_indexes("verdicts")
        }

        assert {"ix_verdicts_ticker_as_of", "ix_verdicts_strategy_as_of"} <= indexes

    def test_legacy_tables_absent_is_not_an_error(self, sqlite_url: str) -> None:
        """A fresh database has nothing legacy to remove."""
        _upgrade(sqlite_url)

        assert not (_tables(sqlite_url) & set(LEGACY_TABLES))


class TestLegacyDropGuard:
    def test_empty_legacy_tables_are_dropped(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            for name in ("signals", "trades", "pos_scans"):
                conn.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)"))

        _upgrade(sqlite_url)

        tables = _tables(sqlite_url)
        assert not (tables & {"signals", "trades", "pos_scans"})
        assert {"verdicts", "insights"} <= tables

    def test_non_empty_legacy_table_aborts_without_dropping_anything(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE signals (id INTEGER PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE trades (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO trades (id) VALUES (1)"))

        with pytest.raises(RuntimeError, match="trades"):
            _upgrade(sqlite_url)

        # Nothing was dropped — the guard runs before the first drop.
        tables = _tables(sqlite_url)
        assert {"signals", "trades"} <= tables
        assert "verdicts" not in tables

    def test_error_names_every_offending_table_with_row_counts(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            for name in ("news", "positions"):
                conn.execute(text(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)"))
                conn.execute(text(f"INSERT INTO {name} (id) VALUES (1)"))

        with pytest.raises(RuntimeError) as excinfo:
            _upgrade(sqlite_url)

        message = str(excinfo.value)
        assert "news" in message and "positions" in message
        assert "1 rows" in message

    def test_unlisted_tables_are_never_touched(self, sqlite_url: str) -> None:
        engine = create_engine(sqlite_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE my_scratch_notes (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO my_scratch_notes (id) VALUES (7)"))

        _upgrade(sqlite_url)

        with engine.connect() as conn:
            remaining = conn.execute(text("SELECT COUNT(*) FROM my_scratch_notes")).scalar_one()
        assert remaining == 1

    def test_legacy_list_covers_the_thirty_known_tables(self) -> None:
        assert len(LEGACY_TABLES) == 30
        assert len(set(LEGACY_TABLES)) == 30


class TestDowngrade:
    def test_downgrade_removes_new_tables(self, migrated_url: str) -> None:
        with _database_url(migrated_url):
            command.downgrade(alembic_config(migrated_url), "base")

        assert not (_tables(migrated_url) & {"verdicts", "insights"})

    def test_downgrade_does_not_resurrect_legacy_tables(self, migrated_url: str) -> None:
        """Fabricating 30 empty tables would imply a rollback path that does not exist."""
        with _database_url(migrated_url):
            command.downgrade(alembic_config(migrated_url), "base")

        assert not (_tables(migrated_url) & set(LEGACY_TABLES))


class TestDialectPortability:
    def test_rls_statements_are_skipped_on_sqlite(self, sqlite_url: str, tmp_path: Path) -> None:
        """SQLite has no RLS; the migration must still complete."""
        _upgrade(sqlite_url)

        assert {"verdicts", "insights"} <= _tables(sqlite_url)

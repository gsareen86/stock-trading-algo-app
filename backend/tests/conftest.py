"""Shared fixtures.

Every fixture builds its own throwaway database and its own ``Settings``. Nothing here
touches a developer's real ``.env`` or the Supabase project.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.settings import PROVIDER_CREDENTIAL_ENV, Settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip provider credentials so a developer's real keys cannot change an assertion.

    Without this, "no provider configured" tests would pass or fail depending on whose
    machine they ran on.
    """
    for env_var in PROVIDER_CREDENTIAL_ENV.values():
        if env_var:
            monkeypatch.delenv(env_var, raising=False)
    for env_var in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "DATABASE_URL"):
        monkeypatch.delenv(env_var, raising=False)


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location", str(BACKEND_ROOT / "app" / "persistence" / "migrations")
    )
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def migrated_url(sqlite_url: str) -> str:
    """A database at head revision."""
    # env.py builds its own Settings; point it at this database for the duration.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sqlite_url
    try:
        command.upgrade(alembic_config(sqlite_url), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    return sqlite_url


@pytest.fixture
def settings(migrated_url: str, tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=migrated_url,
        llm_cache_dir=str(tmp_path / "llm-cache"),
    )


@pytest.fixture
def session_factory(migrated_url: str):
    """Session factory against a migrated throwaway database, schema translation applied."""
    from app.persistence.session import make_engine, make_session_factory

    return make_session_factory(make_engine(Settings(database_url=migrated_url)))


@pytest.fixture
def client(settings: Settings) -> Iterator:
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings)) as test_client:
        yield test_client

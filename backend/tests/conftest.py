"""Shared fixtures.

Every fixture builds its own throwaway database and its own ``Settings``. Nothing here
touches a developer's real ``.env`` or the Supabase project.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.settings import PROVIDER_CREDENTIAL_ENV, Settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Imported here, at collection, for its side effect rather than its API: **importing litellm
# calls `load_dotenv()`**, which copies every line of `backend/.env` into `os.environ`.
#
# That matters because it defeats the obvious defence. `Settings(_env_file=None)` disables the
# *file* rung of the precedence chain, and the values arrive on the *environment* rung instead
# — so a test doing everything right still reads the developer's local model routing. Worse,
# it depended on import order: whichever test first touched the gateway polluted every test
# after it, so the suite passed or failed by collection order.
#
# Forcing the import now makes the pollution happen once, before any test runs, where
# `_isolate_environment` can strip it deterministically.
with contextlib.suppress(ImportError):  # the `llm` extra is optional
    import litellm  # noqa: F401

#: Environment names that belong to this platform's own settings. Derived from the model so a
#: setting added later is isolated because it exists, not because someone remembered.
_SETTINGS_ENV_PREFIXES = tuple(sorted(name.upper() for name in Settings.model_fields))


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cut every ambient configuration source, so an assertion means the same thing anywhere.

    Two of them, and the second was missing until a real ``backend/.env`` was written:

    * **Provider credentials in the environment.** Without this, "no provider configured"
      tests pass or fail depending on whose machine they run on.
    * **The ``.env`` file itself.** ``Settings`` declares ``env_file=".env"``, so the moment
      anyone configures their own machine the way the README tells them to, ten tests asserting
      on *default* routing start reading that developer's model choice instead. A suite that
      only passes on a machine with no local configuration is a suite that fails for every new
      contributor at exactly the wrong moment.

    Tests that need a setting supply it explicitly. That is the point of the precedence chain
    in `platform-configuration` — here it is pinned to its top two rungs, arguments and
    monkeypatched environment, with the file rung removed.
    """
    for env_var in PROVIDER_CREDENTIAL_ENV.values():
        if env_var:
            monkeypatch.delenv(env_var, raising=False)
    for env_var in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "DATABASE_URL"):
        monkeypatch.delenv(env_var, raising=False)

    # Anything a `.env` put on the environment, whether pydantic read the file or litellm
    # copied it there. Removed before the test body runs, so a test that sets one of these
    # itself still wins.
    for name in list(os.environ):
        if name.upper().startswith(_SETTINGS_ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)

    # And the file rung, for anything constructing `Settings()` without `_env_file=None`.
    monkeypatch.setitem(Settings.model_config, "env_file", None)


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
        authenticate(test_client)
        yield test_client


# ── authentication ────────────────────────────────────────────────────────────
#: Credentials every API test logs in with. The password clears the minimum length so the
#: hashing path under test is the real one.
TEST_USERNAME = "tester"
TEST_PASSWORD = "correct-horse-battery-staple"


def authenticate(test_client) -> None:
    """Create the test user and attach a bearer token to every subsequent request.

    Tests exercise endpoints, not the login form, so they authenticate once here rather than
    each carrying the ceremony. `test_authentication.py` is where login itself is tested.
    """
    service = test_client.app.state.auth
    with contextlib.suppress(ValueError):
        # Already created by an earlier client against the same database.
        service.create_user(TEST_USERNAME, TEST_PASSWORD)

    session = service.login(TEST_USERNAME, TEST_PASSWORD)
    test_client.headers.update({"Authorization": f"Bearer {session.access_token}"})


def authed_client(app):
    """A `TestClient` for an app, already logged in."""
    from fastapi.testclient import TestClient

    test_client = TestClient(app)
    authenticate(test_client)
    return test_client


# ── source guards ─────────────────────────────────────────────────────────────
def code_only(source: str) -> str:
    """A module's code with comments and docstrings removed.

    Several tests assert that a module does *not* contain something — no `Ledger` import in the
    broker package, no ranking function in `health`, no verdict aggregation in the surfaces.
    Those modules explain at length *why* they avoid the thing, using the exact words the guard
    searches for, so a naive grep trips on its own documentation. This happened four separate
    times before it became a shared helper.

    Handles Python and TypeScript alike: both use hash or double-slash line comments, and
    triple-quoted or slash-star blocks. Enough for guards that only need to know whether an
    identifier is genuinely used.
    """
    import re

    without_blocks = re.sub(r'"""(?:.|\n)*?"""|/\*(?:.|\n)*?\*/', " ", source)
    return re.sub(r"(?m)^\s*(#|//).*$", " ", without_blocks)


def source_of(package: str, suffix: str = "*.py") -> str:
    """Concatenated code of a package under `app/`, comments stripped."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / package
    return "\n".join(code_only(p.read_text("utf-8")) for p in root.rglob(suffix))

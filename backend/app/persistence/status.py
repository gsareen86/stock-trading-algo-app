"""Database status for the health seam.

Kept apart from the models so ``/health`` can report on the schema without importing the ORM
session machinery it is trying to check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

log = logging.getLogger(__name__)

#: backend/ — the directory holding alembic.ini
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    connected: bool
    current_revision: str | None = None
    head_revision: str | None = None
    migrations_current: bool | None = None
    #: Why the database is not usable, when it isn't. Never contains the connection string.
    reason: str | None = None


def head_revision() -> str | None:
    """The newest revision on disk."""
    try:
        config = Config(str(_BACKEND_ROOT / "alembic.ini"))
        config.set_main_option(
            "script_location", str(_BACKEND_ROOT / "app" / "persistence" / "migrations")
        )
        return ScriptDirectory.from_config(config).get_current_head()
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("could not read head revision: %s", exc)
        return None


def database_status(engine: Engine) -> DatabaseStatus:
    """Connectivity plus how the applied schema compares to head.

    Never raises: an unreachable database is a *reported* state, not an exception, because the
    whole point of this endpoint is to make a broken seam visible.
    """
    head = head_revision()
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            current = row[0] if row else None
    except Exception as exc:
        # Distinguish "cannot connect" from "connected, but never migrated".
        try:
            with engine.connect():
                pass
        except Exception as connect_exc:
            return DatabaseStatus(
                connected=False,
                head_revision=head,
                reason=type(connect_exc).__name__,
            )
        log.debug("alembic_version unreadable: %s", exc)
        return DatabaseStatus(
            connected=True,
            current_revision=None,
            head_revision=head,
            migrations_current=False,
            reason="alembic_version table absent — migrations have never run",
        )

    return DatabaseStatus(
        connected=True,
        current_revision=current,
        head_revision=head,
        migrations_current=(current == head) if (current and head) else False,
    )

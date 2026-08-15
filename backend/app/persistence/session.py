"""Engine and session construction.

Built from an injected ``Settings`` rather than a module-level singleton, so tests can point
at a throwaway database without patching imports.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.persistence.base import SQLITE_SCHEMA_TRANSLATE


def make_engine(settings: Settings) -> Engine:
    """Create an engine for the configured database.

    On SQLite the ``trading`` schema is translated away, so the same models work against a
    file database in dev and a namespaced Postgres schema in prod.
    """
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if settings.is_sqlite:
        # SQLite has no connection pool worth configuring, and the pre-ping is meaningless
        # against a local file.
        kwargs.pop("pool_pre_ping")

    engine = create_engine(settings.database_url, **kwargs)
    if settings.is_sqlite:
        engine = engine.execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

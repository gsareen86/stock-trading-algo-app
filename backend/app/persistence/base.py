"""SQLAlchemy declarative base and schema namespacing.

This platform lives in its own Postgres schema, ``trading``. Thirty pre-existing tables stay
where they are, in ``public``, holding ~47.5k rows. Namespacing keeps this platform's schema
clean without destroying any of that, and makes "is this table ours?" answerable from its
namespace alone. Nothing here reads those tables.

SQLite has no schemas. Rather than maintain a second set of models, the ``trading`` namespace
is translated away for SQLite connections via SQLAlchemy's ``schema_translate_map`` — one
model definition, both dialects, which is the rule this rebuild holds to.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

#: Postgres schema owning every table this platform creates.
SCHEMA = "trading"

#: Applied to SQLite connections, where ``trading`` collapses to the single namespace.
SQLITE_SCHEMA_TRANSLATE: dict[str, None] = {SCHEMA: None}


class Base(DeclarativeBase):
    """Declarative base for every persisted model."""

    metadata = MetaData(schema=SCHEMA)

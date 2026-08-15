"""SQLAlchemy declarative base and schema namespacing.

The rebuilt platform lives in its own Postgres schema, ``trading``. The predecessor's 30
tables stay where they are, in ``public``, holding ~47.5k rows of real history — trades,
positions and signal outcomes that later increments will want for backtesting. Namespacing
keeps the rebuild clean without destroying any of it, and makes "is this the new app or the
old one?" answerable from the table name alone.

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

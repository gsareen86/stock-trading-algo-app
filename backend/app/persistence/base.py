"""SQLAlchemy declarative base.

One set of model definitions serves both SQLite (dev/test) and PostgreSQL (prod). There is
deliberately no dialect-specific model — the predecessor's hand-rolled dual-dialect schema,
with no migration path between them, is one of the things this rebuild removes.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every persisted model."""

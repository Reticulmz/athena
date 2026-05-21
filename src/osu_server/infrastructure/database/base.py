"""Declarative base for SQLAlchemy ORM models.

All ORM models should inherit from ``Base`` so that Alembic can
auto-detect schema changes.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

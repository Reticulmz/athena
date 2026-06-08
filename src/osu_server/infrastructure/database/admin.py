"""Database administration helpers for local development tasks."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

_MAINTENANCE_DATABASE = "postgres"


def to_asyncpg_url(database_url: str) -> URL:
    """Return a PostgreSQL URL using the asyncpg SQLAlchemy driver."""
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        return url.set(drivername="postgresql+asyncpg")
    if url.drivername == "postgresql+asyncpg":
        return url
    msg = f"Unsupported database driver for PostgreSQL admin task: {url.drivername}"
    raise ValueError(msg)


def maintenance_url_for(database_url: str) -> tuple[URL, str]:
    """Return the maintenance DB URL and target database name."""
    target_url = to_asyncpg_url(database_url)
    target_database = target_url.database
    if not target_database:
        msg = "DATABASE_URL must include a database name"
        raise ValueError(msg)
    return target_url.set(database=_MAINTENANCE_DATABASE), target_database


def quote_identifier(identifier: str) -> str:
    """Quote a PostgreSQL identifier for DDL statements."""
    if "\x00" in identifier:
        msg = "PostgreSQL identifiers cannot contain NUL bytes"
        raise ValueError(msg)
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


async def create_database_if_missing(database_url: str) -> bool:
    """Create the target database if it does not already exist."""
    maintenance_url, target_database = maintenance_url_for(database_url)
    engine = create_async_engine(
        maintenance_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": target_database},
            )
            if result.first() is not None:
                return False
            create_database = text(f"CREATE DATABASE {quote_identifier(target_database)}")
            _ = await connection.execute(create_database)
            return True
    finally:
        await engine.dispose()

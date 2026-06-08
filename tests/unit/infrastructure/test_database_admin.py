"""Tests for local database administration helpers."""

import pytest

from osu_server.infrastructure.database.admin import (
    maintenance_url_for,
    quote_identifier,
    to_asyncpg_url,
)


def test_to_asyncpg_url_converts_standard_postgresql_url() -> None:
    url = to_asyncpg_url("postgresql://localhost:5432/athena_test")

    assert url.drivername == "postgresql+asyncpg"
    assert url.database == "athena_test"


def test_to_asyncpg_url_keeps_asyncpg_url() -> None:
    url = to_asyncpg_url("postgresql+asyncpg://localhost:5432/athena_test")

    assert url.drivername == "postgresql+asyncpg"
    assert url.database == "athena_test"


def test_to_asyncpg_url_rejects_non_postgresql_driver() -> None:
    with pytest.raises(ValueError, match="Unsupported database driver"):
        _ = to_asyncpg_url("mysql://localhost/athena_test")


def test_maintenance_url_for_targets_postgres_database() -> None:
    maintenance_url, target_database = maintenance_url_for(
        "postgresql://localhost:5432/athena_test"
    )

    assert maintenance_url.drivername == "postgresql+asyncpg"
    assert maintenance_url.database == "postgres"
    assert target_database == "athena_test"


def test_maintenance_url_for_requires_database_name() -> None:
    with pytest.raises(ValueError, match="database name"):
        _ = maintenance_url_for("postgresql://localhost:5432")


def test_quote_identifier_escapes_double_quotes() -> None:
    assert quote_identifier('athena"test') == '"athena""test"'


def test_quote_identifier_rejects_nul_bytes() -> None:
    with pytest.raises(ValueError, match="NUL"):
        _ = quote_identifier("athena\x00test")

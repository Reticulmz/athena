"""local database administration helperの変換とvalidation契約を検証するmodule."""

import pytest

from osu_server.infrastructure.database.admin import (
    maintenance_url_for,
    quote_identifier,
    to_asyncpg_url,
)


def test_to_asyncpg_url_converts_standard_postgresql_url() -> None:
    """標準PostgreSQL URLを変換しasyncpg driverとdatabase名を検証する.

    Returns:
        None: URL変換結果を検証して値を返さず完了する.
    """
    url = to_asyncpg_url("postgresql://localhost:5432/athena_test")

    assert url.drivername == "postgresql+asyncpg"
    assert url.database == "athena_test"


def test_to_asyncpg_url_keeps_asyncpg_url() -> None:
    """Asyncpg URLを変換しdriverとdatabase名を維持することを検証する.

    Returns:
        None: URL変換結果を検証して値を返さず完了する.
    """
    url = to_asyncpg_url("postgresql+asyncpg://localhost:5432/athena_test")

    assert url.drivername == "postgresql+asyncpg"
    assert url.database == "athena_test"


def test_to_asyncpg_url_rejects_non_postgresql_driver() -> None:
    """MySQL URLを変換しValueErrorを送出することを検証する.

    Returns:
        None: unsupported driver例外を検証して値を返さず完了する.
    """
    with pytest.raises(ValueError, match="Unsupported database driver"):
        _ = to_asyncpg_url("mysql://localhost/athena_test")


def test_maintenance_url_for_targets_postgres_database() -> None:
    """Target database URLからpostgres maintenance URLと対象名を生成することを検証する.

    Returns:
        None: maintenance connection情報を検証して値を返さず完了する.
    """
    maintenance_url, target_database = maintenance_url_for(
        "postgresql://localhost:5432/athena_test"
    )

    assert maintenance_url.drivername == "postgresql+asyncpg"
    assert maintenance_url.database == "postgres"
    assert target_database == "athena_test"


def test_maintenance_url_for_requires_database_name() -> None:
    """database名なしのPostgreSQL URLを渡しValueErrorを送出することを検証する.

    Returns:
        None: missing database例外を検証して値を返さず完了する.
    """
    with pytest.raises(ValueError, match="database name"):
        _ = maintenance_url_for("postgresql://localhost:5432")


def test_quote_identifier_escapes_double_quotes() -> None:
    """Double quoteを含むidentifierをquoteし内部quoteをescapeすることを検証する.

    Returns:
        None: quoted identifierを検証して値を返さず完了する.
    """
    assert quote_identifier('athena"test') == '"athena""test"'


def test_quote_identifier_rejects_nul_bytes() -> None:
    """NUL byteを含むidentifierをquoteしValueErrorを送出することを検証する.

    Returns:
        None: invalid identifier例外を検証して値を返さず完了する.
    """
    with pytest.raises(ValueError, match="NUL"):
        _ = quote_identifier("athena\x00test")

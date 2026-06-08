from __future__ import annotations

from athena_cli.env.dsn import (
    DatabaseConnectionParts,
    ValkeyConnectionParts,
    build_database_dsn,
    build_valkey_dsn,
)
from osu_server.config import AppConfig


def test_database_dsn_url_encodes_parts_and_masks_password() -> None:
    dsn = build_database_dsn(
        DatabaseConnectionParts(
            host="localhost",
            port=5432,
            database="osu test/db",
            username="user name",
            password="p@ss:/word",
        )
    )

    assert dsn.value == (
        "postgresql+asyncpg://user%20name:p%40ss%3A%2Fword@localhost:5432/osu%20test%2Fdb"
    )
    assert dsn.masked_value == (
        "postgresql+asyncpg://user%20name:********@localhost:5432/osu%20test%2Fdb"
    )
    assert "p@ss" not in dsn.masked_value


def test_valkey_dsn_url_encodes_parts_and_masks_password() -> None:
    dsn = build_valkey_dsn(
        ValkeyConnectionParts(
            host="localhost",
            port=6379,
            database=2,
            username="default",
            password="p@ss word",
        )
    )

    assert dsn.value == "redis://default:p%40ss%20word@localhost:6379/2"
    assert dsn.masked_value == "redis://default:********@localhost:6379/2"
    assert "p@ss" not in dsn.masked_value


def test_generated_dsns_are_accepted_by_app_config() -> None:
    database_dsn = build_database_dsn(
        DatabaseConnectionParts(
            host="localhost",
            port=5432,
            database="athena",
            username="athena",
            password="secret",
        )
    )
    valkey_dsn = build_valkey_dsn(
        ValkeyConnectionParts(
            host="localhost",
            port=6379,
            database=0,
            username=None,
            password=None,
        )
    )

    config = AppConfig.model_validate(
        {"database_url": database_dsn.value, "valkey_url": valkey_dsn.value}
    )

    assert str(config.database_url) == database_dsn.value
    assert str(config.valkey_url) == valkey_dsn.value

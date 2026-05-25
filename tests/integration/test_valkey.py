# pyright: reportAny=false, reportUnknownMemberType=false, reportGeneralTypeIssues=false, reportUnknownVariableType=false
"""Integration tests for Valkey connection infrastructure.

These tests require a running Valkey instance. The connection URL is read
from the ``VALKEY_URL`` environment variable.
"""

import os
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, cast

import pytest
from glide import ExpirySet, ExpiryType, GlideClient

if TYPE_CHECKING:
    from glide_shared.constants import TEncodable

from osu_server.infrastructure.cache.valkey_client import create_valkey_client

_KEY_PREFIX = "athena_test:"


def _get_valkey_url() -> str:
    url = os.environ.get("VALKEY_URL")
    if not url:
        pytest.skip("VALKEY_URL not set")
    return url


@pytest.fixture
async def valkey_client() -> AsyncGenerator[GlideClient]:
    client = await create_valkey_client(_get_valkey_url())
    yield client
    # Clean up any test keys
    cursor: str = "0"
    while True:
        next_cursor, keys = await client.scan(cursor, match=f"{_KEY_PREFIX}*", count=100)
        if keys:
            _ = await client.delete(cast("list[TEncodable]", keys))
        cursor = next_cursor.decode() if isinstance(next_cursor, bytes) else str(next_cursor)
        if cursor == "0":
            break
    await client.close()


class TestValkeyConnection:
    """Tests for Valkey client creation and connectivity."""

    async def test_create_valkey_client_returns_glide_instance(
        self,
        valkey_client: GlideClient,
    ) -> None:
        assert isinstance(valkey_client, GlideClient)

    async def test_valkey_client_connects_to_server(
        self,
        valkey_client: GlideClient,
    ) -> None:
        result = await valkey_client.ping()
        assert isinstance(result, bytes)


class TestValkeyOperations:
    """Tests for basic async Valkey operations (set/get/delete)."""

    async def test_set_and_get(
        self,
        valkey_client: GlideClient,
    ) -> None:
        key = f"{_KEY_PREFIX}test_set_get"
        _ = await valkey_client.set(key, "hello")
        value = await valkey_client.get(key)
        assert value == b"hello"

    async def test_get_nonexistent_key_returns_none(
        self,
        valkey_client: GlideClient,
    ) -> None:
        value = await valkey_client.get(f"{_KEY_PREFIX}nonexistent")
        assert value is None

    async def test_delete_removes_key(
        self,
        valkey_client: GlideClient,
    ) -> None:
        key = f"{_KEY_PREFIX}test_delete"
        _ = await valkey_client.set(key, "to_delete")
        deleted_count = await valkey_client.delete([key])
        assert deleted_count == 1
        value = await valkey_client.get(key)
        assert value is None

    async def test_set_with_expiry(
        self,
        valkey_client: GlideClient,
    ) -> None:
        key = f"{_KEY_PREFIX}test_expiry"
        _ = await valkey_client.set(key, "expires", expiry=ExpirySet(ExpiryType.SEC, 3600))
        ttl = await valkey_client.ttl(key)
        assert isinstance(ttl, int)
        assert ttl > 0


class TestValkeyClose:
    """Tests for Valkey client close behaviour."""

    async def test_close_closes_connection(self) -> None:
        client = await create_valkey_client(_get_valkey_url())
        # Verify connectivity first
        result = await client.ping()
        assert isinstance(result, bytes)
        await client.close()

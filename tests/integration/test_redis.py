# pyright: reportAny=false, reportUnknownMemberType=false, reportGeneralTypeIssues=false, reportUnknownVariableType=false
"""Integration tests for Redis connection infrastructure.

These tests require a running Redis instance. The connection URL is read
from the ``REDIS_URL`` environment variable.
"""

import os
from collections.abc import AsyncGenerator

import pytest
from redis.asyncio import Redis

from osu_server.infrastructure.cache.redis_client import create_redis_client

_KEY_PREFIX = "athena_test:"


def _get_redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set")
    return url


@pytest.fixture
async def redis_client() -> AsyncGenerator[Redis]:
    client = create_redis_client(_get_redis_url())
    yield client
    # Clean up any test keys
    keys = await client.keys(f"{_KEY_PREFIX}*")
    if keys:
        await client.delete(*keys)
    await client.aclose()


class TestRedisConnection:
    """Tests for Redis client creation and connectivity."""

    async def test_create_redis_client_returns_redis_instance(
        self,
        redis_client: Redis,
    ) -> None:
        assert isinstance(redis_client, Redis)

    async def test_redis_client_connects_to_server(
        self,
        redis_client: Redis,
    ) -> None:
        result = await redis_client.ping()
        assert result is True


class TestRedisOperations:
    """Tests for basic async Redis operations (set/get/delete)."""

    async def test_set_and_get(
        self,
        redis_client: Redis,
    ) -> None:
        key = f"{_KEY_PREFIX}test_set_get"
        await redis_client.set(key, "hello")
        value = await redis_client.get(key)
        assert value == b"hello"

    async def test_get_nonexistent_key_returns_none(
        self,
        redis_client: Redis,
    ) -> None:
        value = await redis_client.get(f"{_KEY_PREFIX}nonexistent")
        assert value is None

    async def test_delete_removes_key(
        self,
        redis_client: Redis,
    ) -> None:
        key = f"{_KEY_PREFIX}test_delete"
        await redis_client.set(key, "to_delete")
        deleted_count = await redis_client.delete(key)
        assert deleted_count == 1
        value = await redis_client.get(key)
        assert value is None

    async def test_set_with_expiry(
        self,
        redis_client: Redis,
    ) -> None:
        key = f"{_KEY_PREFIX}test_expiry"
        await redis_client.set(key, "expires", ex=3600)
        ttl = await redis_client.ttl(key)
        assert isinstance(ttl, int)
        assert ttl > 0


class TestRedisClose:
    """Tests for Redis client close behaviour."""

    async def test_aclose_closes_connection(self) -> None:
        client = create_redis_client(_get_redis_url())
        # Verify connectivity first
        assert await client.ping() is True
        await client.aclose()

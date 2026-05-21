# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""Integration tests for RedisSessionStore against a real Redis instance.

These tests mirror the unit tests for InMemorySessionStore but run against
real Redis.  They can also be parameterized to run both implementations
through the same test matrix.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from redis.asyncio import Redis

from osu_server.infrastructure.cache.redis_client import create_redis_client
from osu_server.infrastructure.state.interfaces.session_store import SessionStore
from osu_server.infrastructure.state.memory.session_store import InMemorySessionStore
from osu_server.infrastructure.state.redis.session_store import RedisSessionStore

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
    # Clean up all test keys
    for pattern in (f"{_KEY_PREFIX}session:*", f"{_KEY_PREFIX}user_session:*"):
        keys = await client.keys(pattern)
        if keys:
            await client.delete(*keys)
    await client.aclose()


@pytest.fixture
def redis_store(redis_client: Redis) -> RedisSessionStore:
    return RedisSessionStore(redis_client, ttl=3600, key_prefix=_KEY_PREFIX)


@pytest.fixture
def memory_store() -> InMemorySessionStore:
    return InMemorySessionStore()


# ---------------------------------------------------------------------------
# Parametrized fixture: both implementations share the same test suite
# ---------------------------------------------------------------------------


@pytest.fixture(params=["redis", "memory"])
def store(
    request: pytest.FixtureRequest,
    redis_store: RedisSessionStore,
    memory_store: InMemorySessionStore,
) -> SessionStore:
    if request.param == "redis":
        return redis_store
    return memory_store


# ---------------------------------------------------------------------------
# Tests — run for BOTH implementations via the parametrized ``store`` fixture
# ---------------------------------------------------------------------------


class TestSessionStoreProtocolCompliance:
    """RedisSessionStore satisfies the SessionStore Protocol."""

    def test_redis_session_store_is_session_store(
        self,
        redis_store: RedisSessionStore,
    ) -> None:
        assert isinstance(redis_store, SessionStore)


class TestCreateAndGet:
    """create stores session data; get retrieves it by token."""

    async def test_create_and_get(self, store: SessionStore) -> None:
        data: dict[str, object] = {"username": "peppy", "privileges": 1}
        await store.create(user_id=1, token="abc-123", data=data)

        result = await store.get("abc-123")

        assert result is not None
        assert result["username"] == "peppy"
        assert result["privileges"] == 1

    async def test_get_nonexistent_returns_none(self, store: SessionStore) -> None:
        result = await store.get("nonexistent-token")

        assert result is None


class TestGetByUser:
    """get_by_user retrieves session data by user_id."""

    async def test_get_by_user(self, store: SessionStore) -> None:
        data: dict[str, object] = {"username": "peppy", "privileges": 1}
        await store.create(user_id=1, token="abc-123", data=data)

        result = await store.get_by_user(user_id=1)

        assert result is not None
        assert result["username"] == "peppy"

    async def test_get_by_user_nonexistent_returns_none(self, store: SessionStore) -> None:
        result = await store.get_by_user(user_id=9999)

        assert result is None


class TestDelete:
    """delete removes the session; subsequent get returns None."""

    async def test_delete(self, store: SessionStore) -> None:
        data: dict[str, object] = {"username": "peppy"}
        await store.create(user_id=1, token="abc-123", data=data)

        await store.delete("abc-123")

        assert await store.get("abc-123") is None
        assert await store.get_by_user(user_id=1) is None

    async def test_delete_nonexistent_is_noop(self, store: SessionStore) -> None:
        # Should not raise
        await store.delete("nonexistent-token")


class TestExists:
    """exists checks for token presence."""

    async def test_exists_true(self, store: SessionStore) -> None:
        data: dict[str, object] = {"username": "peppy"}
        await store.create(user_id=1, token="abc-123", data=data)

        assert await store.exists("abc-123") is True

    async def test_exists_false(self, store: SessionStore) -> None:
        assert await store.exists("nonexistent-token") is False


class TestOverwrite:
    """Same user_id with a new token replaces the old session entirely."""

    async def test_create_overwrites_previous_session(self, store: SessionStore) -> None:
        data_old: dict[str, object] = {"username": "peppy", "version": "old"}
        data_new: dict[str, object] = {"username": "peppy", "version": "new"}

        await store.create(user_id=1, token="old-token", data=data_old)
        await store.create(user_id=1, token="new-token", data=data_new)

        # Old token should be gone
        assert await store.get("old-token") is None
        assert await store.exists("old-token") is False

        # New token should be active
        result = await store.get("new-token")
        assert result is not None
        assert result["version"] == "new"

        # get_by_user returns the new session
        result_by_user = await store.get_by_user(user_id=1)
        assert result_by_user is not None
        assert result_by_user["version"] == "new"

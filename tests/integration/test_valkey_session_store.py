"""Integration tests for ValkeySessionStore against a real Valkey instance.

These tests mirror the unit tests for InMemorySessionStore but run against
real Valkey.  They can also be parameterized to run both implementations
through the same test matrix.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from glide import GlideClient
    from glide_shared.constants import TEncodable

from osu_server.domain.session import SessionData
from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.valkey.session_store import ValkeySessionStore

_KEY_PREFIX = "athena_test:"

_SESSION = SessionData(
    user_id=1,
    username="peppy",
    privileges=1,
    country="JP",
    osu_version="20231111",
    utc_offset=9,
    display_city=True,
    client_hashes="hash1:hash2",
    pm_private=False,
    role_ids=(1, 2),
)


def _get_valkey_url() -> str:
    url = os.environ.get("VALKEY_URL")
    if not url:
        pytest.skip("VALKEY_URL not set")
    return url


@pytest.fixture
async def valkey_client() -> AsyncGenerator[GlideClient]:
    client = await create_valkey_client(_get_valkey_url())
    yield client
    # Clean up all test keys
    for pattern in (f"{_KEY_PREFIX}session:*", f"{_KEY_PREFIX}user_session:*"):
        cursor: str = "0"
        while True:
            next_cursor, keys = await client.scan(cursor, match=pattern, count=100)
            if keys:
                _ = await client.delete(cast("list[TEncodable]", keys))
            cursor = next_cursor.decode() if isinstance(next_cursor, bytes) else str(next_cursor)
            if cursor == "0":
                break
    await client.close()


@pytest.fixture
def valkey_store(valkey_client: GlideClient) -> ValkeySessionStore:
    return ValkeySessionStore(valkey_client, ttl=3600, key_prefix=_KEY_PREFIX)


@pytest.fixture
def memory_store() -> InMemorySessionStore:
    return InMemorySessionStore()


# ---------------------------------------------------------------------------
# Parametrized fixture: both implementations share the same test suite
# ---------------------------------------------------------------------------


@pytest.fixture(params=["valkey", "memory"])
def store(
    request: pytest.FixtureRequest,
    valkey_store: ValkeySessionStore,
    memory_store: InMemorySessionStore,
) -> SessionStore:
    param: str = request.param  # pyright: ignore[reportAny]
    if param == "valkey":
        return valkey_store
    return memory_store


# ---------------------------------------------------------------------------
# Tests — run for BOTH implementations via the parametrized ``store`` fixture
# ---------------------------------------------------------------------------


class TestSessionStoreProtocolCompliance:
    """ValkeySessionStore satisfies the SessionStore Protocol."""

    def test_valkey_session_store_is_session_store(
        self,
        valkey_store: ValkeySessionStore,
    ) -> None:
        assert isinstance(valkey_store, SessionStore)


class TestCreateAndGet:
    """create stores session data; get retrieves it by token."""

    async def test_create_and_get(self, store: SessionStore) -> None:
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        result = await store.get("abc-123")

        assert result is not None
        assert result.username == "peppy"
        assert result.privileges == 1
        assert result.role_ids == (1, 2)

    async def test_get_nonexistent_returns_none(self, store: SessionStore) -> None:
        result = await store.get("nonexistent-token")

        assert result is None


class TestGetByUser:
    """get_by_user retrieves session data by user_id."""

    async def test_get_by_user(self, store: SessionStore) -> None:
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        result = await store.get_by_user(user_id=1)

        assert result is not None
        assert result.username == "peppy"

    async def test_get_by_user_nonexistent_returns_none(self, store: SessionStore) -> None:
        result = await store.get_by_user(user_id=9999)

        assert result is None


class TestDelete:
    """delete removes the session; subsequent get returns None."""

    async def test_delete(self, store: SessionStore) -> None:
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        await store.delete("abc-123")

        assert await store.get("abc-123") is None
        assert await store.get_by_user(user_id=1) is None

    async def test_delete_nonexistent_is_noop(self, store: SessionStore) -> None:
        # Should not raise
        await store.delete("nonexistent-token")


class TestExists:
    """exists checks for token presence."""

    async def test_exists_true(self, store: SessionStore) -> None:
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        assert await store.exists("abc-123") is True

    async def test_exists_false(self, store: SessionStore) -> None:
        assert await store.exists("nonexistent-token") is False


class TestOverwrite:
    """Same user_id with a new token replaces the old session entirely."""

    async def test_create_overwrites_previous_session(self, store: SessionStore) -> None:
        data_old = replace(_SESSION, country="US")
        data_new = replace(_SESSION, country="JP")

        await store.create(user_id=1, token="old-token", data=data_old)
        await store.create(user_id=1, token="new-token", data=data_new)

        # Old token should be gone
        assert await store.get("old-token") is None
        assert await store.exists("old-token") is False

        # New token should be active
        result = await store.get("new-token")
        assert result is not None
        assert result.country == "JP"

        # get_by_user returns the new session
        result_by_user = await store.get_by_user(user_id=1)
        assert result_by_user is not None
        assert result_by_user.country == "JP"

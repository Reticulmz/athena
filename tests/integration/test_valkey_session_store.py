"""Integration tests for ValkeySessionStore against a real Valkey instance.

These tests mirror the unit tests for InMemorySessionStore but run against
real Valkey.  They can also be parameterized to run both implementations
through the same test matrix.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from glide import GlideClient
    from glide_shared.constants import TEncodable

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import SessionAuthorization, SessionData
from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.valkey.session_store import ValkeySessionStore
from tests.support.service_availability import require_tcp_service_url

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
    return require_tcp_service_url("VALKEY_URL", default_port=6379)


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
def store(request: pytest.FixtureRequest) -> SessionStore:
    param = cast("str", request.param)
    if param == "valkey":
        return cast("SessionStore", request.getfixturevalue("valkey_store"))
    return cast("SessionStore", request.getfixturevalue("memory_store"))


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


class TestListActiveSessions:
    """list_active_sessions returns only active session data."""

    async def test_empty_store_returns_empty_list(self, store: SessionStore) -> None:
        result = await store.list_active_sessions()

        assert result == []

    async def test_returns_active_sessions(self, store: SessionStore) -> None:
        session_2 = replace(_SESSION, user_id=2, username="cookiezi")

        await store.create(user_id=1, token="abc-123", data=_SESSION)
        await store.create(user_id=2, token="def-456", data=session_2)

        result = await store.list_active_sessions()

        assert sorted(session.user_id for session in result) == [1, 2]

    async def test_excludes_deleted_sessions(self, store: SessionStore) -> None:
        session_2 = replace(_SESSION, user_id=2, username="cookiezi")

        await store.create(user_id=1, token="abc-123", data=_SESSION)
        await store.create(user_id=2, token="def-456", data=session_2)
        await store.delete_by_user(user_id=1)

        result = await store.list_active_sessions()

        assert [session.user_id for session in result] == [2]


# ---------------------------------------------------------------------------
# Tests — update_authorization
# ---------------------------------------------------------------------------


class TestUpdateAuthorization:
    """update_authorization patches privileges and role_ids while preserving
    all other fields and the user-to-token mapping."""

    async def test_update_authorization_patches_session(
        self,
        store: SessionStore,
    ) -> None:
        """privileges and role_ids are updated to the new values."""
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        new_auth = SessionAuthorization(
            privileges=Privileges.ADMIN,
            role_ids=(5, 6),
        )
        result = await store.update_authorization(user_id=1, authorization=new_auth)

        assert result is True

        session = await store.get_by_user(user_id=1)
        assert session is not None
        assert session.privileges == int(Privileges.ADMIN)
        assert session.role_ids == (5, 6)

    async def test_update_authorization_preserves_token_mapping(
        self,
        store: SessionStore,
    ) -> None:
        """user-to-token mapping still references the same token."""
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        _ = await store.update_authorization(
            user_id=1,
            authorization=SessionAuthorization(
                privileges=Privileges.MODERATOR,
                role_ids=(3,),
            ),
        )

        # Same token still retrievable
        result = await store.get("abc-123")
        assert result is not None
        assert result.user_id == 1

        # get_by_user still works
        by_user = await store.get_by_user(user_id=1)
        assert by_user is not None
        assert by_user.privileges == int(Privileges.MODERATOR)

    async def test_update_authorization_preserves_non_auth_fields(
        self,
        store: SessionStore,
    ) -> None:
        """username, country, osu_version, and other fields are unchanged."""
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        _ = await store.update_authorization(
            user_id=1,
            authorization=SessionAuthorization(
                privileges=Privileges.SUPPORTER,
                role_ids=(2,),
            ),
        )

        result = await store.get_by_user(user_id=1)
        assert result is not None
        assert result.username == _SESSION.username
        assert result.country == _SESSION.country
        assert result.osu_version == _SESSION.osu_version
        assert result.utc_offset == _SESSION.utc_offset
        assert result.display_city == _SESSION.display_city
        assert result.client_hashes == _SESSION.client_hashes
        assert result.pm_private == _SESSION.pm_private

    async def test_update_authorization_returns_false_when_no_session(
        self,
        store: SessionStore,
    ) -> None:
        """Returns False when the user has no active session."""
        result = await store.update_authorization(
            user_id=9999,
            authorization=SessionAuthorization(
                privileges=Privileges.NORMAL,
                role_ids=(),
            ),
        )

        assert result is False

        # No session was created
        assert await store.get_by_user(user_id=9999) is None

    async def test_update_authorization_idempotent(
        self,
        store: SessionStore,
    ) -> None:
        """Repeated calls with the same authorization produce the same result."""
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        auth = SessionAuthorization(
            privileges=Privileges.DEVELOPER,
            role_ids=(7,),
        )
        first = await store.update_authorization(user_id=1, authorization=auth)
        second = await store.update_authorization(user_id=1, authorization=auth)

        assert first is True
        assert second is True

        result = await store.get_by_user(user_id=1)
        assert result is not None
        assert result.privileges == int(Privileges.DEVELOPER)
        assert result.role_ids == (7,)

    async def test_update_authorization_preserves_ttl(
        self,
        valkey_client: GlideClient,
        valkey_store: ValkeySessionStore,
    ) -> None:
        """TTL is not reset after update_authorization.

        Valkey-specific test because the in-memory store has no TTL concept.
        """
        await valkey_store.create(
            user_id=1,
            token="abc-123",
            data=_SESSION,
        )

        # Reduce TTL so we can detect a difference
        _ = await valkey_client.expire(f"{_KEY_PREFIX}session:abc-123", 1800)
        _ = await valkey_client.expire(f"{_KEY_PREFIX}user_session:1", 1800)

        _ = await valkey_store.update_authorization(
            user_id=1,
            authorization=SessionAuthorization(
                privileges=Privileges.MODERATOR,
                role_ids=(3,),
            ),
        )

        # TTL should still be around 1800 (not reset to the constructor default 3600)
        session_ttl = await valkey_client.ttl(f"{_KEY_PREFIX}session:abc-123")
        user_ttl = await valkey_client.ttl(f"{_KEY_PREFIX}user_session:1")

        assert session_ttl > 0
        assert session_ttl <= 1800
        assert user_ttl > 0
        assert user_ttl <= 1800


# ---------------------------------------------------------------------------
# Tests — update_pm_private
# ---------------------------------------------------------------------------


class TestUpdatePmPrivate:
    """update_pm_private patches pm_private while preserving session state."""

    async def test_update_pm_private_patches_session(
        self,
        store: SessionStore,
    ) -> None:
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        enabled = await store.update_pm_private(user_id=1, enabled=True)
        disabled = await store.update_pm_private(user_id=1, enabled=False)

        assert enabled is True
        assert disabled is True
        session = await store.get_by_user(user_id=1)
        assert session is not None
        assert session.pm_private is False

    async def test_update_pm_private_preserves_token_mapping(
        self,
        store: SessionStore,
    ) -> None:
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        _ = await store.update_pm_private(user_id=1, enabled=True)

        result = await store.get("abc-123")
        assert result is not None
        assert result.user_id == 1
        assert result.pm_private is True

        by_user = await store.get_by_user(user_id=1)
        assert by_user is not None
        assert by_user.pm_private is True

    async def test_update_pm_private_preserves_non_privacy_fields(
        self,
        store: SessionStore,
    ) -> None:
        await store.create(user_id=1, token="abc-123", data=_SESSION)

        _ = await store.update_pm_private(user_id=1, enabled=True)

        result = await store.get_by_user(user_id=1)
        assert result is not None
        assert result.user_id == _SESSION.user_id
        assert result.username == _SESSION.username
        assert result.privileges == _SESSION.privileges
        assert result.role_ids == _SESSION.role_ids
        assert result.country == _SESSION.country
        assert result.osu_version == _SESSION.osu_version
        assert result.utc_offset == _SESSION.utc_offset
        assert result.display_city == _SESSION.display_city
        assert result.client_hashes == _SESSION.client_hashes
        assert result.silence_end == _SESSION.silence_end

    async def test_update_pm_private_returns_false_when_no_session(
        self,
        store: SessionStore,
    ) -> None:
        result = await store.update_pm_private(user_id=9999, enabled=True)

        assert result is False
        assert await store.get_by_user(user_id=9999) is None

    async def test_update_pm_private_preserves_ttl(
        self,
        valkey_client: GlideClient,
        valkey_store: ValkeySessionStore,
    ) -> None:
        await valkey_store.create(
            user_id=1,
            token="abc-123",
            data=_SESSION,
        )

        _ = await valkey_client.expire(f"{_KEY_PREFIX}session:abc-123", 1800)
        _ = await valkey_client.expire(f"{_KEY_PREFIX}user_session:1", 1800)

        _ = await valkey_store.update_pm_private(user_id=1, enabled=True)

        session_ttl = await valkey_client.ttl(f"{_KEY_PREFIX}session:abc-123")
        user_ttl = await valkey_client.ttl(f"{_KEY_PREFIX}user_session:1")

        assert session_ttl > 0
        assert session_ttl <= 1800
        assert user_ttl > 0
        assert user_ttl <= 1800

    async def test_update_pm_private_returns_false_when_session_key_is_missing(
        self,
        valkey_client: GlideClient,
        valkey_store: ValkeySessionStore,
    ) -> None:
        await valkey_store.create(
            user_id=1,
            token="abc-123",
            data=_SESSION,
        )
        _ = await valkey_client.delete([f"{_KEY_PREFIX}session:abc-123"])

        result = await valkey_store.update_pm_private(user_id=1, enabled=True)

        assert result is False
        assert await valkey_store.get_by_user(user_id=1) is None

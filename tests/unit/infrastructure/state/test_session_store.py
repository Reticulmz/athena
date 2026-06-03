"""Tests for SessionStore Protocol + InMemorySessionStore (TDD — RED phase first)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from osu_server.domain.role import Privileges
from osu_server.domain.session import SessionData
from osu_server.domain.session_authorization import SessionAuthorization
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.session_store import InMemorySessionStore

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
)


@pytest.fixture
def store() -> InMemorySessionStore:
    return InMemorySessionStore()


async def test_create_and_get(store: InMemorySessionStore) -> None:
    """create stores session data; get retrieves it by token."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    result = await store.get("abc-123")

    assert result is not None
    assert result.username == "peppy"
    assert result.privileges == 1


async def test_get_nonexistent_returns_none(store: InMemorySessionStore) -> None:
    """get on unknown token returns None."""
    result = await store.get("nonexistent-token")

    assert result is None


async def test_get_by_user(store: InMemorySessionStore) -> None:
    """get_by_user retrieves session data by user_id."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    result = await store.get_by_user(user_id=1)

    assert result is not None
    assert result.username == "peppy"


async def test_get_by_user_nonexistent_returns_none(store: InMemorySessionStore) -> None:
    """get_by_user for unknown user_id returns None."""
    result = await store.get_by_user(user_id=9999)

    assert result is None


async def test_delete(store: InMemorySessionStore) -> None:
    """delete removes the session; subsequent get returns None."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    await store.delete("abc-123")

    assert await store.get("abc-123") is None
    assert await store.get_by_user(user_id=1) is None


async def test_exists_true(store: InMemorySessionStore) -> None:
    """exists returns True for a created session."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    assert await store.exists("abc-123") is True


async def test_exists_false(store: InMemorySessionStore) -> None:
    """exists returns False for an unknown token."""
    assert await store.exists("nonexistent-token") is False


async def test_create_overwrites_previous_session(store: InMemorySessionStore) -> None:
    """Same user_id with a new token replaces the old session entirely."""
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


async def test_refresh_existing_token(store: InMemorySessionStore) -> None:
    """refresh returns True for an existing session."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    result = await store.refresh("abc-123")

    assert result is True


async def test_refresh_nonexistent_token(store: InMemorySessionStore) -> None:
    """refresh returns False for an unknown token."""
    result = await store.refresh("nonexistent-token")

    assert result is False


# ---------------------------------------------------------------------------
# delete_by_user
# ---------------------------------------------------------------------------


async def test_delete_by_user_removes_session(store: InMemorySessionStore) -> None:
    """delete_by_user removes the session for the given user_id."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    await store.delete_by_user(user_id=1)

    assert await store.get("abc-123") is None
    assert await store.get_by_user(user_id=1) is None
    assert await store.exists("abc-123") is False


async def test_delete_by_user_idempotent(store: InMemorySessionStore) -> None:
    """delete_by_user on a non-existent user_id is a no-op (no error)."""
    # Should not raise
    await store.delete_by_user(user_id=9999)


async def test_delete_by_user_does_not_affect_other_users(store: InMemorySessionStore) -> None:
    """delete_by_user only removes the targeted user's session."""
    other_session = replace(_SESSION, user_id=2, username="cookiezi")
    await store.create(user_id=1, token="token-1", data=_SESSION)
    await store.create(user_id=2, token="token-2", data=other_session)

    await store.delete_by_user(user_id=1)

    assert await store.get("token-1") is None
    result = await store.get("token-2")
    assert result is not None
    assert result.username == "cookiezi"


# ---------------------------------------------------------------------------
# get_all_user_ids
# ---------------------------------------------------------------------------


async def test_get_all_user_ids_empty_store(store: InMemorySessionStore) -> None:
    """get_all_user_ids returns an empty list when the store is empty."""
    result = await store.get_all_user_ids()

    assert result == []


async def test_get_all_user_ids_returns_all(store: InMemorySessionStore) -> None:
    """get_all_user_ids returns all active user_ids."""
    session_2 = replace(_SESSION, user_id=2, username="cookiezi")
    session_3 = replace(_SESSION, user_id=3, username="whitecat")

    await store.create(user_id=1, token="t1", data=_SESSION)
    await store.create(user_id=2, token="t2", data=session_2)
    await store.create(user_id=3, token="t3", data=session_3)

    result = await store.get_all_user_ids()

    assert sorted(result) == [1, 2, 3]


async def test_get_all_user_ids_excludes_deleted(store: InMemorySessionStore) -> None:
    """get_all_user_ids does not include users whose sessions were deleted."""
    session_2 = replace(_SESSION, user_id=2, username="cookiezi")
    await store.create(user_id=1, token="t1", data=_SESSION)
    await store.create(user_id=2, token="t2", data=session_2)

    await store.delete_by_user(user_id=1)

    result = await store.get_all_user_ids()

    assert result == [2]


# ---------------------------------------------------------------------------
# update_authorization (Feature Flag Protocol — RED phase with flag OFF)
# ---------------------------------------------------------------------------


async def test_update_authorization_updates_privileges_and_role_ids(
    store: InMemorySessionStore,
) -> None:
    """update_authorization updates privileges and role_ids on the active session."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.NORMAL | Privileges.MODERATOR,
        role_ids=(1, 2),
    )
    result = await store.update_authorization(user_id=1, authorization=new_auth)

    assert result is True
    session = await store.get("abc-123")
    assert session is not None
    assert session.privileges == int(Privileges.NORMAL | Privileges.MODERATOR)
    assert session.role_ids == (1, 2)


async def test_update_authorization_preserves_other_fields(
    store: InMemorySessionStore,
) -> None:
    """update_authorization preserves all non-authorization session fields."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.MODERATOR,
        role_ids=(3,),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session = await store.get("abc-123")
    assert session is not None
    assert session.user_id == 1
    assert session.username == "peppy"
    assert session.country == "JP"
    assert session.osu_version == "20231111"
    assert session.utc_offset == 9
    assert session.display_city is True
    assert session.client_hashes == "hash1:hash2"
    assert session.pm_private is False
    assert session.silence_end == 0


async def test_update_authorization_preserves_token_lookup(
    store: InMemorySessionStore,
) -> None:
    """After update_authorization, get(token) returns the updated session."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.NORMAL,
        role_ids=(),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session = await store.get("abc-123")
    assert session is not None
    assert session.privileges == int(Privileges.NORMAL)
    assert session.role_ids == ()


async def test_update_authorization_preserves_user_lookup(
    store: InMemorySessionStore,
) -> None:
    """After update_authorization, get_by_user(user_id) returns the updated session."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.VERIFIED,
        role_ids=(5,),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session = await store.get_by_user(user_id=1)
    assert session is not None
    assert session.privileges == int(Privileges.VERIFIED)
    assert session.role_ids == (5,)


async def test_update_authorization_returns_false_for_offline_user(
    store: InMemorySessionStore,
) -> None:
    """update_authorization returns False for a user without an active session."""
    new_auth = SessionAuthorization(
        privileges=Privileges.NORMAL,
        role_ids=(),
    )
    result = await store.update_authorization(user_id=9999, authorization=new_auth)

    assert result is False
    assert await store.get_by_user(user_id=9999) is None
    assert await store.get_all_user_ids() == []


async def test_update_authorization_does_not_affect_other_users(
    store: InMemorySessionStore,
) -> None:
    """update_authorization only modifies the targeted user's session."""
    other_session = replace(_SESSION, user_id=2, username="cookiezi")
    await store.create(user_id=1, token="token-1", data=_SESSION)
    await store.create(user_id=2, token="token-2", data=other_session)

    new_auth = SessionAuthorization(
        privileges=Privileges.MODERATOR,
        role_ids=(1,),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session1 = await store.get("token-1")
    assert session1 is not None
    assert session1.privileges == int(Privileges.MODERATOR)

    session2 = await store.get("token-2")
    assert session2 is not None
    assert session2.privileges == 1  # original _SESSION value unchanged


async def test_update_authorization_idempotent(
    store: InMemorySessionStore,
) -> None:
    """Repeated update_authorization with the same authorization has the same result."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.SUPPORTER | Privileges.VERIFIED,
        role_ids=(1, 2),
    )
    result1 = await store.update_authorization(user_id=1, authorization=new_auth)
    result2 = await store.update_authorization(user_id=1, authorization=new_auth)

    assert result1 is True
    assert result2 is True
    session = await store.get("abc-123")
    assert session is not None
    assert session.privileges == int(Privileges.SUPPORTER | Privileges.VERIFIED)
    assert session.role_ids == (1, 2)


async def test_update_authorization_token_mapping_unchanged(
    store: InMemorySessionStore,
) -> None:
    """update_authorization does not change token-to-user or user-to-token mappings."""
    await store.create(user_id=1, token="abc-123", data=_SESSION)

    new_auth = SessionAuthorization(
        privileges=Privileges.NONE,
        role_ids=(),
    )
    _ = await store.update_authorization(user_id=1, authorization=new_auth)

    session_by_user = await store.get_by_user(user_id=1)
    assert session_by_user is not None
    assert session_by_user.user_id == 1

    session_by_token = await store.get("abc-123")
    assert session_by_token is not None
    assert session_by_token.user_id == 1


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


async def test_inmemory_session_store_is_instance_of_session_store() -> None:
    """InMemorySessionStore is recognized as a SessionStore Protocol instance."""
    store = InMemorySessionStore()

    assert isinstance(store, SessionStore)

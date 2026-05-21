"""Tests for SessionStore Protocol + InMemorySessionStore (TDD — RED phase first)."""

from __future__ import annotations

import pytest

from osu_server.infrastructure.state.memory.session_store import InMemorySessionStore


@pytest.fixture
def store() -> InMemorySessionStore:
    return InMemorySessionStore()


async def test_create_and_get(store: InMemorySessionStore) -> None:
    """create stores session data; get retrieves it by token."""
    data: dict[str, object] = {"username": "peppy", "privileges": 1}
    await store.create(user_id=1, token="abc-123", data=data)

    result = await store.get("abc-123")

    assert result is not None
    assert result["username"] == "peppy"
    assert result["privileges"] == 1


async def test_get_nonexistent_returns_none(store: InMemorySessionStore) -> None:
    """get on unknown token returns None."""
    result = await store.get("nonexistent-token")

    assert result is None


async def test_get_by_user(store: InMemorySessionStore) -> None:
    """get_by_user retrieves session data by user_id."""
    data: dict[str, object] = {"username": "peppy", "privileges": 1}
    await store.create(user_id=1, token="abc-123", data=data)

    result = await store.get_by_user(user_id=1)

    assert result is not None
    assert result["username"] == "peppy"


async def test_get_by_user_nonexistent_returns_none(store: InMemorySessionStore) -> None:
    """get_by_user for unknown user_id returns None."""
    result = await store.get_by_user(user_id=9999)

    assert result is None


async def test_delete(store: InMemorySessionStore) -> None:
    """delete removes the session; subsequent get returns None."""
    data: dict[str, object] = {"username": "peppy"}
    await store.create(user_id=1, token="abc-123", data=data)

    await store.delete("abc-123")

    assert await store.get("abc-123") is None
    assert await store.get_by_user(user_id=1) is None


async def test_exists_true(store: InMemorySessionStore) -> None:
    """exists returns True for a created session."""
    data: dict[str, object] = {"username": "peppy"}
    await store.create(user_id=1, token="abc-123", data=data)

    assert await store.exists("abc-123") is True


async def test_exists_false(store: InMemorySessionStore) -> None:
    """exists returns False for an unknown token."""
    assert await store.exists("nonexistent-token") is False


async def test_create_overwrites_previous_session(store: InMemorySessionStore) -> None:
    """Same user_id with a new token replaces the old session entirely."""
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

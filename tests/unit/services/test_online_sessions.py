"""Tests for active online session query use-case."""

from __future__ import annotations

from dataclasses import replace

from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.services.queries.identity import (
    GetActiveSessionsByUserIdsQueryInput,
    GetActiveSessionsByUserIdsQueryUseCase,
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryUseCase,
    OnlineSessionSnapshot,
)

_SESSION = SessionData(
    user_id=1,
    username="peppy",
    privileges=1,
    country="JP",
    osu_version="20231111",
    utc_offset=9,
    display_city=False,
    client_hashes="hashes",
    pm_private=False,
)


async def test_list_active_sessions_returns_empty_tuple_when_no_sessions() -> None:
    store = InMemorySessionStore()
    use_case = ListActiveSessionsQueryUseCase(session_store=store)

    result = await use_case.execute(ListActiveSessionsQueryInput())

    assert result.sessions == ()


async def test_list_active_sessions_returns_snapshot_tuple_sorted_by_user_id() -> None:
    store = InMemorySessionStore()
    use_case = ListActiveSessionsQueryUseCase(session_store=store)
    session_2 = replace(_SESSION, user_id=2, username="cookiezi", country="US", utc_offset=-5)

    await store.create(user_id=2, token="t2", data=session_2)
    await store.create(user_id=1, token="t1", data=_SESSION)

    result = await use_case.execute(ListActiveSessionsQueryInput())

    assert result.sessions == (
        OnlineSessionSnapshot(
            user_id=1,
            username="peppy",
            privileges=1,
            country="JP",
            utc_offset=9,
        ),
        OnlineSessionSnapshot(
            user_id=2,
            username="cookiezi",
            privileges=1,
            country="US",
            utc_offset=-5,
        ),
    )


async def test_list_active_sessions_does_not_synthesize_banchobot() -> None:
    store = InMemorySessionStore()
    use_case = ListActiveSessionsQueryUseCase(session_store=store)

    result = await use_case.execute(ListActiveSessionsQueryInput())

    assert all(session.user_id != BANCHO_BOT_IDENTITY.user_id for session in result.sessions)


async def test_list_active_sessions_reflects_deleted_sessions() -> None:
    store = InMemorySessionStore()
    use_case = ListActiveSessionsQueryUseCase(session_store=store)
    session_2 = replace(_SESSION, user_id=2, username="cookiezi")

    await store.create(user_id=1, token="t1", data=_SESSION)
    await store.create(user_id=2, token="t2", data=session_2)
    await store.delete_by_user(user_id=1)

    result = await use_case.execute(ListActiveSessionsQueryInput())

    assert tuple(session.user_id for session in result.sessions) == (2,)


async def test_get_active_sessions_by_user_ids_returns_requested_online_sessions() -> None:
    store = InMemorySessionStore()
    use_case = GetActiveSessionsByUserIdsQueryUseCase(session_store=store)
    session_2 = replace(_SESSION, user_id=2, username="cookiezi", country="US", utc_offset=-5)

    await store.create(user_id=1, token="t1", data=_SESSION)
    await store.create(user_id=2, token="t2", data=session_2)

    result = await use_case.execute(GetActiveSessionsByUserIdsQueryInput(user_ids=(2, 99, 1)))

    assert result.sessions == (
        OnlineSessionSnapshot(
            user_id=2,
            username="cookiezi",
            privileges=1,
            country="US",
            utc_offset=-5,
        ),
        OnlineSessionSnapshot(
            user_id=1,
            username="peppy",
            privileges=1,
            country="JP",
            utc_offset=9,
        ),
    )


async def test_get_active_sessions_by_user_ids_deduplicates_lookup_order() -> None:
    store = InMemorySessionStore()
    use_case = GetActiveSessionsByUserIdsQueryUseCase(session_store=store)

    await store.create(user_id=1, token="t1", data=_SESSION)

    result = await use_case.execute(GetActiveSessionsByUserIdsQueryInput(user_ids=(1, 1, 1)))

    assert tuple(session.user_id for session in result.sessions) == (1,)

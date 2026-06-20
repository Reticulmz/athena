"""Online session query use-case boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import SessionData
    from osu_server.repositories.interfaces.session_store import (
        ActiveSessionRoster,
        UserSessionLookup,
    )


@dataclass(slots=True, frozen=True)
class OnlineSessionSnapshot:
    """Read-only snapshot of the session fields needed for online presence."""

    user_id: int
    username: str
    privileges: int
    country: str
    utc_offset: int

    @classmethod
    def from_session(cls, session: SessionData) -> OnlineSessionSnapshot:
        return cls(
            user_id=session.user_id,
            username=session.username,
            privileges=session.privileges,
            country=session.country,
            utc_offset=session.utc_offset,
        )


@dataclass(slots=True, frozen=True)
class ListActiveSessionsQueryInput: ...


@dataclass(slots=True, frozen=True)
class ListActiveSessionsQueryResult:
    sessions: tuple[OnlineSessionSnapshot, ...]


@dataclass(slots=True, frozen=True)
class GetActiveSessionsByUserIdsQueryInput:
    """指定ユーザー ID の active session だけを読む query input。"""

    user_ids: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class GetActiveSessionsByUserIdsQueryResult:
    """指定ユーザー ID の active session snapshot。"""

    sessions: tuple[OnlineSessionSnapshot, ...]


class ListActiveSessionsQuery(Protocol):
    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult: ...


class GetActiveSessionsByUserIdsQuery(Protocol):
    async def execute(
        self,
        input_data: GetActiveSessionsByUserIdsQueryInput,
    ) -> GetActiveSessionsByUserIdsQueryResult: ...


class ListActiveSessionsQueryUseCase:
    """Read active online session snapshots."""

    _session_store: ActiveSessionRoster

    def __init__(self, *, session_store: ActiveSessionRoster) -> None:
        self._session_store = session_store

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        _ = input_data
        sessions = await self._session_store.list_active_sessions()
        snapshots = tuple(
            sorted(
                (OnlineSessionSnapshot.from_session(session) for session in sessions),
                key=lambda snapshot: snapshot.user_id,
            )
        )
        return ListActiveSessionsQueryResult(sessions=snapshots)


class GetActiveSessionsByUserIdsQueryUseCase:
    """指定ユーザー ID の active online session snapshot を読む。"""

    _session_store: UserSessionLookup

    def __init__(self, *, session_store: UserSessionLookup) -> None:
        self._session_store = session_store

    async def execute(
        self,
        input_data: GetActiveSessionsByUserIdsQueryInput,
    ) -> GetActiveSessionsByUserIdsQueryResult:
        snapshots: list[OnlineSessionSnapshot] = []
        for user_id in dict.fromkeys(input_data.user_ids):
            session = await self._session_store.get_by_user(user_id)
            if session is not None:
                snapshots.append(OnlineSessionSnapshot.from_session(session))

        return GetActiveSessionsByUserIdsQueryResult(sessions=tuple(snapshots))


__all__ = [
    "GetActiveSessionsByUserIdsQuery",
    "GetActiveSessionsByUserIdsQueryInput",
    "GetActiveSessionsByUserIdsQueryResult",
    "GetActiveSessionsByUserIdsQueryUseCase",
    "ListActiveSessionsQuery",
    "ListActiveSessionsQueryInput",
    "ListActiveSessionsQueryResult",
    "ListActiveSessionsQueryUseCase",
    "OnlineSessionSnapshot",
]

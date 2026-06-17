"""Online session query use-case boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.sessions import SessionData


class _SessionStore(Protocol):
    async def list_active_sessions(self) -> list[SessionData]: ...


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


class ListActiveSessionsQuery(Protocol):
    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult: ...


class ListActiveSessionsQueryUseCase:
    """Read active online session snapshots."""

    _session_store: _SessionStore

    def __init__(self, *, session_store: _SessionStore) -> None:
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


__all__ = [
    "ListActiveSessionsQuery",
    "ListActiveSessionsQueryInput",
    "ListActiveSessionsQueryResult",
    "ListActiveSessionsQueryUseCase",
    "OnlineSessionSnapshot",
]

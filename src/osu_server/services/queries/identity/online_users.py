"""Online user query use-case boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _OnlineUsersService(Protocol):
    async def get_all_user_ids(self) -> list[int]: ...


@dataclass(slots=True, frozen=True)
class ListOnlineUsersQueryInput: ...


@dataclass(slots=True, frozen=True)
class ListOnlineUsersQueryResult:
    user_ids: tuple[int, ...]


class ListOnlineUsersQuery(Protocol):
    async def execute(
        self,
        input_data: ListOnlineUsersQueryInput,
    ) -> ListOnlineUsersQueryResult: ...


class ListOnlineUsersQueryUseCase:
    """Read all active session user IDs."""

    _online_users_service: _OnlineUsersService

    def __init__(self, *, online_users_service: _OnlineUsersService) -> None:
        self._online_users_service = online_users_service

    async def execute(self, input_data: ListOnlineUsersQueryInput) -> ListOnlineUsersQueryResult:
        _ = input_data
        user_ids = await self._online_users_service.get_all_user_ids()
        return ListOnlineUsersQueryResult(user_ids=tuple(user_ids))


__all__ = [
    "ListOnlineUsersQuery",
    "ListOnlineUsersQueryInput",
    "ListOnlineUsersQueryResult",
    "ListOnlineUsersQueryUseCase",
]

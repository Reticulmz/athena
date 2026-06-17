"""Friend relationship query use-cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.friends import (
        FriendRelationshipQueryRepository,
    )


@dataclass(frozen=True, slots=True)
class ListFriendIdsQueryInput:
    owner_user_id: int


@dataclass(frozen=True, slots=True)
class ListFriendIdsQueryResult:
    friend_user_ids: tuple[int, ...]


class ListFriendIdsQueryUseCase(Protocol):
    async def execute(
        self,
        input_data: ListFriendIdsQueryInput,
    ) -> ListFriendIdsQueryResult: ...


class CheckFriendRelationshipQueryUseCase(Protocol):
    async def execute(self, *, owner_user_id: int, target_user_id: int) -> bool: ...


class GetFriendEligibleUserIdsQueryUseCase(Protocol):
    async def execute(self, *, viewer_user_id: int) -> tuple[int, ...]: ...


class ListFriendIdsQuery:
    """Read owner-scoped friend target IDs."""

    def __init__(self, *, repository: FriendRelationshipQueryRepository) -> None:
        self._repository: FriendRelationshipQueryRepository = repository

    async def execute(
        self,
        input_data: ListFriendIdsQueryInput,
    ) -> ListFriendIdsQueryResult:
        friend_user_ids = await self._repository.list_friend_ids(input_data.owner_user_id)
        return ListFriendIdsQueryResult(friend_user_ids=friend_user_ids)


class CheckFriendRelationshipQuery:
    """Read whether an owner explicitly friended a target."""

    def __init__(self, *, repository: FriendRelationshipQueryRepository) -> None:
        self._repository: FriendRelationshipQueryRepository = repository

    async def execute(self, *, owner_user_id: int, target_user_id: int) -> bool:
        return await self._repository.has_relationship(owner_user_id, target_user_id)


class GetFriendEligibleUserIdsQuery:
    """Provide the Friends leaderboard eligible user ID source."""

    def __init__(self, *, repository: FriendRelationshipQueryRepository) -> None:
        self._repository: FriendRelationshipQueryRepository = repository

    async def execute(self, *, viewer_user_id: int) -> tuple[int, ...]:
        return await self._repository.list_friend_ids(viewer_user_id)


__all__ = [
    "CheckFriendRelationshipQuery",
    "CheckFriendRelationshipQueryUseCase",
    "GetFriendEligibleUserIdsQuery",
    "GetFriendEligibleUserIdsQueryUseCase",
    "ListFriendIdsQuery",
    "ListFriendIdsQueryInput",
    "ListFriendIdsQueryResult",
    "ListFriendIdsQueryUseCase",
]

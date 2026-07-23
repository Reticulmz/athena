"""Friend relationshipを読むread-only query use-caseを定義するmodule.

owner単位のfriend target確認とFriends leaderboard用user ID集合を提供する.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.friends import (
        FriendRelationshipQueryRepository,
    )


@dataclass(frozen=True, slots=True)
class ListFriendIdsQueryInput:
    """ownerのfriend target IDを列挙するquery inputを表す.

    Attributes:
        owner_user_id (int): friend relationshipのownerとなるuserの識別子.
    """

    owner_user_id: int


@dataclass(frozen=True, slots=True)
class ListFriendIdsQueryResult:
    """ownerが登録したfriend target ID群のquery結果を表す.

    Attributes:
        friend_user_ids (tuple[int, ...]): ownerが明示的に登録したtarget user ID群.
    """

    friend_user_ids: tuple[int, ...]


class ListFriendIdsQueryUseCase(Protocol):
    """owner単位のfriend target IDを列挙するquery protocolを表す."""

    async def execute(
        self,
        input_data: ListFriendIdsQueryInput,
    ) -> ListFriendIdsQueryResult:
        """指定ownerのfriend target ID群を返す.

        Args:
            input_data (ListFriendIdsQueryInput): ownerを指定するquery input.

        Returns:
            ListFriendIdsQueryResult: ownerが登録したtarget user ID群を含む結果.
        """
        ...


class CheckFriendRelationshipQueryUseCase(Protocol):
    """ownerからtargetへのfriend relationshipを確認するquery protocolを表す."""

    async def execute(self, *, owner_user_id: int, target_user_id: int) -> bool:
        """指定した一方向relationshipが存在するかを返す.

        Args:
            owner_user_id (int): relationshipを登録したowner userの識別子.
            target_user_id (int): ownerがfriendとして登録したか確認するtarget userの識別子.

        Returns:
            bool: ownerからtargetへのrelationshipが存在する場合はTrue.
        """
        ...


class GetFriendEligibleUserIdsQueryUseCase(Protocol):
    """Friends leaderboardに表示可能なuser ID群を取得するquery protocolを表す."""

    async def execute(self, *, viewer_user_id: int) -> tuple[int, ...]:
        """viewer本人とfriend targetのuser ID群を返す.

        Args:
            viewer_user_id (int): Friends表示を要求したviewer userの識別子.

        Returns:
            tuple[int, ...]: viewer本人を先頭に含むfriend eligible user ID群.
        """
        ...


class ListFriendIdsQuery:
    """owner単位のfriend target IDを読むquery use-caseを表す.

    Attributes:
        _repository (FriendRelationshipQueryRepository): owner単位relationshipを読む
            query repository.
    """

    def __init__(self, *, repository: FriendRelationshipQueryRepository) -> None:
        """Friend relationship query repositoryを設定する.

        Args:
            repository (FriendRelationshipQueryRepository): owner単位relationshipを読むrepository.
        """
        self._repository: FriendRelationshipQueryRepository = repository

    async def execute(
        self,
        input_data: ListFriendIdsQueryInput,
    ) -> ListFriendIdsQueryResult:
        """指定ownerが登録したfriend target ID群を取得する.

        Args:
            input_data (ListFriendIdsQueryInput): ownerを指定するquery input.

        Returns:
            ListFriendIdsQueryResult: ownerが登録したtarget user ID群を含む結果.
        """
        friend_user_ids = await self._repository.list_friend_ids(input_data.owner_user_id)
        return ListFriendIdsQueryResult(friend_user_ids=friend_user_ids)


class CheckFriendRelationshipQuery:
    """ownerがtargetをfriend登録したか読むquery use-caseを表す.

    Attributes:
        _repository (FriendRelationshipQueryRepository): 一方向relationshipを読むquery repository.
    """

    def __init__(self, *, repository: FriendRelationshipQueryRepository) -> None:
        """Friend relationship query repositoryを設定する.

        Args:
            repository (FriendRelationshipQueryRepository): 一方向relationshipを読むrepository.
        """
        self._repository: FriendRelationshipQueryRepository = repository

    async def execute(self, *, owner_user_id: int, target_user_id: int) -> bool:
        """指定ownerからtargetへのfriend relationshipを確認する.

        Args:
            owner_user_id (int): relationshipを登録したowner userの識別子.
            target_user_id (int): friend登録を確認するtarget userの識別子.

        Returns:
            bool: ownerからtargetへのrelationshipが存在する場合はTrue.
        """
        return await self._repository.has_relationship(owner_user_id, target_user_id)


class GetFriendEligibleUserIdsQuery:
    """Friends leaderboardに表示可能なuser ID群を提供するquery use-caseを表す.

    Attributes:
        _repository (FriendRelationshipQueryRepository): viewerのfriend targetを読む
            query repository.
    """

    def __init__(self, *, repository: FriendRelationshipQueryRepository) -> None:
        """Friend relationship query repositoryを設定する.

        Args:
            repository (FriendRelationshipQueryRepository): viewerのfriend targetを読むrepository.
        """
        self._repository: FriendRelationshipQueryRepository = repository

    async def execute(self, *, viewer_user_id: int) -> tuple[int, ...]:
        """viewer本人を含むFriends leaderboard対象user ID群を取得する.

        Args:
            viewer_user_id (int): Friends表示を要求したviewer userの識別子.

        Returns:
            tuple[int, ...]: viewer本人を先頭に含むfriend eligible user ID群.

        Notes:
            viewerへ向かうreverse relationshipだけは対象に含めない.
        """
        friend_user_ids = await self._repository.list_friend_ids(viewer_user_id)
        return (viewer_user_id, *friend_user_ids)


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

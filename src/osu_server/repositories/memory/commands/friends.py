"""In-memory command 側 friend relationship repository を実装する module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.identity.friends import FriendRelationship
from osu_server.repositories.memory.commands.state import (
    InMemoryFriendRelationshipRecord,
    now_utc,
)

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryFriendRelationshipCommandRepository:
    """有向 friend relationship の存在確認, 作成, 削除を command 用に管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.

        Returns:
            None: state への参照を保持したことを示す.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def target_exists(self, user_id: int) -> bool:
        """Friend target として指定した user ID が主記録に存在するか返す.

        Args:
            user_id (int): 存在確認する user の識別子.

        Returns:
            bool: users_by_id に user ID が存在する場合は True.
        """
        return user_id in self._state.users_by_id

    async def add_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """有向 friend relationship を未登録の場合だけ追加する.

        Args:
            owner_user_id (int): friend list を所有する user の識別子.
            target_user_id (int): owner が friend として追加する user の識別子.

        Returns:
            bool: 新しい relationship を保存した場合は True. すでに同じ edge があれば False.

        Raises:
            ValueError: owner_user_id と target_user_id が同一で FriendRelationship が拒否する場合.

        Notes:
            user 主記録の存在は検証しない. 成功時は現在 UTC 時刻を持つ record を保存する.
        """
        relationship = FriendRelationship(
            owner_user_id=owner_user_id,
            target_user_id=target_user_id,
        )
        key = (relationship.owner_user_id, relationship.target_user_id)
        if key in self._state.friend_relationships_by_key:
            return False

        self._state.friend_relationships_by_key[key] = InMemoryFriendRelationshipRecord(
            owner_user_id=relationship.owner_user_id,
            target_user_id=relationship.target_user_id,
            created_at=now_utc(),
        )
        return True

    async def remove_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """有向 friend relationship を存在する場合だけ削除する.

        Args:
            owner_user_id (int): friend list を所有する user の識別子.
            target_user_id (int): owner が削除する friend の識別子.

        Returns:
            bool: relationship を削除した場合は True. 未登録なら False.
        """
        key = (owner_user_id, target_user_id)
        if key not in self._state.friend_relationships_by_key:
            return False

        del self._state.friend_relationships_by_key[key]
        return True

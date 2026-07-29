"""Friend relationship 用 read-only query repository contract を定義する."""

from __future__ import annotations

from typing import Protocol


class FriendRelationshipQueryRepository(Protocol):
    """Owner scoped friend relationship への read-only access を定義する.

    Notes:
        この Protocol は relationship projection を読むだけであり追加や削除を行わない.
        Command Unit of Work を開かず transaction の commit/rollback も所有しない.
    """

    async def list_friend_ids(self, owner_user_id: int) -> tuple[int, ...]:
        """Owner が登録した friend target ID を返す.

        Args:
            owner_user_id (int): Relationship の owner User ID.

        Returns:
            tuple[int, ...]: Owner が登録した friend target User ID. 対象がない場合は空の tuple.
        """
        ...

    async def has_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """Owner が target を friend として登録済みかを返す.

        Args:
            owner_user_id (int): Relationship の owner User ID.
            target_user_id (int): 確認する friend target User ID.

        Returns:
            bool: Owner が target を明示的に登録済みの場合は `True`. それ以外は `False`.
        """
        ...

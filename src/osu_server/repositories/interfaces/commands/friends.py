"""Friend relationship mutation の command-side repository 契約."""

from __future__ import annotations

from typing import Protocol


class FriendRelationshipCommandRepository(Protocol):
    """Friend relationship の mutation と consistency-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def target_exists(self, user_id: int) -> bool:
        """Friend target identity が durable に存在するかを返す.

        Args:
            user_id (int): 確認する friend target の User ID.

        Returns:
            bool: Target identity が存在する場合は True.存在しない場合は False.
        """
        ...

    async def add_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """Directed relationship を永続化し row を作成したか返す.

        Args:
            owner_user_id (int): Relationship を所有する User ID.
            target_user_id (int): Friend として追加する target User ID.

        Returns:
            bool: 新しい relationship row を作成した場合は True.既存 row なら False.
        """
        ...

    async def remove_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """Directed relationship を削除し row を削除したか返す.

        Args:
            owner_user_id (int): Relationship を所有する User ID.
            target_user_id (int): Friend から削除する target User ID.

        Returns:
            bool: Relationship row を削除した場合は True.存在しない場合は False.
        """
        ...

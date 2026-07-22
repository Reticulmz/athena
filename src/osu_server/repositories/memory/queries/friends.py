"""Committed in-memory state から Friend Relationship を読む query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryFriendRelationshipQueryRepository:
    """Committed in-memory state を読む read-only Friend Relationship repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, friendship state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.

        Returns:
            None: factory を保持する repository を構築する.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def list_friend_ids(self, owner_user_id: int) -> tuple[int, ...]:
        """Owner User の friend target IDs を作成日時順で取得する.

        Args:
            owner_user_id (int): relationship の owner User ID.

        Returns:
            tuple[int, ...]: created_at, target_user_id の昇順で並べた target User IDs.
            記録がなければ空の tuple.
        """
        state = self._factory.snapshot()
        records = [
            record
            for record in state.friend_relationships_by_key.values()
            if record.owner_user_id == owner_user_id
        ]
        records.sort(key=lambda record: (record.created_at, record.target_user_id))
        return tuple(record.target_user_id for record in records)

    async def has_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """方向付き Friend Relationship が存在するかを返す.

        Args:
            owner_user_id (int): relationship の owner User ID.
            target_user_id (int): relationship の target User ID.

        Returns:
            bool: owner から target への key が snapshot にあれば True, それ以外は False.
        """
        state = self._factory.snapshot()
        return (owner_user_id, target_user_id) in state.friend_relationships_by_key

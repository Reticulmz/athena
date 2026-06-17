"""In-memory query-side friend relationship repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryFriendRelationshipQueryRepository:
    """Read-only friend relationship adapter over committed memory state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def list_friend_ids(self, owner_user_id: int) -> tuple[int, ...]:
        state = self._factory.snapshot()
        records = [
            record
            for record in state.friend_relationships_by_key.values()
            if record.owner_user_id == owner_user_id
        ]
        records.sort(key=lambda record: (record.created_at, record.target_user_id))
        return tuple(record.target_user_id for record in records)

    async def has_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        state = self._factory.snapshot()
        return (owner_user_id, target_user_id) in state.friend_relationships_by_key

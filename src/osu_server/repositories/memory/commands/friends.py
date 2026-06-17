"""In-memory command-side friend relationship repository."""

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
    """Friend command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def target_exists(self, user_id: int) -> bool:
        return user_id in self._state.users_by_id

    async def add_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
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
        key = (owner_user_id, target_user_id)
        if key not in self._state.friend_relationships_by_key:
            return False

        del self._state.friend_relationships_by_key[key]
        return True

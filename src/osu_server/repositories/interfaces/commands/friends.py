"""Command-side friend relationship repository contract."""

from __future__ import annotations

from typing import Protocol


class FriendRelationshipCommandRepository(Protocol):
    """Mutation and consistency-check port for friend relationships."""

    async def target_exists(self, user_id: int) -> bool:
        """Return whether a friend target identity exists durably."""
        ...

    async def add_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """Persist a directed relationship and return whether a row was created."""
        ...

    async def remove_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """Remove a directed relationship and return whether a row was removed."""
        ...

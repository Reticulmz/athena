"""Query-side friend relationship repository contract."""

from __future__ import annotations

from typing import Protocol


class FriendRelationshipQueryRepository(Protocol):
    """Read-only access to owner-scoped friend relationships."""

    async def list_friend_ids(self, owner_user_id: int) -> tuple[int, ...]:
        """Return friend target IDs owned by *owner_user_id*."""
        ...

    async def has_relationship(self, owner_user_id: int, target_user_id: int) -> bool:
        """Return whether owner has explicitly added target."""
        ...

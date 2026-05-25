"""ChannelStateStore Protocol — abstract interface for channel membership management."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ChannelStateStore(Protocol):
    """Protocol for channel membership state operations.

    Implementations must maintain a bidirectional index:
    channel -> members and user -> channels.

    Methods: add_member, remove_member, is_member, get_members,
    get_member_count, get_user_channels, remove_user_from_all.
    """

    async def add_member(self, channel_name: str, user_id: int) -> None:
        """Add a user to a channel.

        Both the channel->members and user->channels indices are updated atomically.
        Idempotent: adding an already-present member is a no-op.
        """
        ...

    async def remove_member(self, channel_name: str, user_id: int) -> None:
        """Remove a user from a channel.

        Both the channel->members and user->channels indices are updated atomically.
        Idempotent: removing a non-member is a no-op.
        """
        ...

    async def is_member(self, channel_name: str, user_id: int) -> bool:
        """Return True if the user is a member of the channel."""
        ...

    async def get_members(self, channel_name: str) -> set[int]:
        """Return the set of user IDs in the given channel.

        Returns an empty set if the channel has no members.
        """
        ...

    async def get_member_count(self, channel_name: str) -> int:
        """Return the number of members in the given channel."""
        ...

    async def get_user_channels(self, user_id: int) -> set[str]:
        """Return the set of channel names the user has joined.

        Returns an empty set if the user has not joined any channels.
        """
        ...

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        """Remove the user from all channels they have joined.

        Returns the set of channel names the user was removed from.
        Returns an empty set if the user was not in any channel.
        """
        ...

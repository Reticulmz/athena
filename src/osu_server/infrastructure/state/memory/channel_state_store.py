"""InMemoryChannelStateStore — dict-based channel membership store for testing."""

from __future__ import annotations


class InMemoryChannelStateStore:
    """In-memory implementation of the ChannelStateStore Protocol.

    Uses two bidirectional dicts:
    - ``_channel_members``: channel_name -> set of user_ids
    - ``_user_channels``: user_id -> set of channel_names

    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._channel_members: dict[str, set[int]] = {}
        self._user_channels: dict[int, set[str]] = {}

    async def add_member(self, channel_name: str, user_id: int) -> None:
        """Add a user to a channel.  Idempotent."""
        self._channel_members.setdefault(channel_name, set()).add(user_id)
        self._user_channels.setdefault(user_id, set()).add(channel_name)

    async def remove_member(self, channel_name: str, user_id: int) -> None:
        """Remove a user from a channel.  Idempotent."""
        members = self._channel_members.get(channel_name)
        if members is not None:
            members.discard(user_id)
            if not members:
                del self._channel_members[channel_name]

        channels = self._user_channels.get(user_id)
        if channels is not None:
            channels.discard(channel_name)
            if not channels:
                del self._user_channels[user_id]

    async def is_member(self, channel_name: str, user_id: int) -> bool:
        """Return True if the user is a member of the channel."""
        members = self._channel_members.get(channel_name)
        if members is None:
            return False
        return user_id in members

    async def get_members(self, channel_name: str) -> set[int]:
        """Return the set of user IDs in the given channel."""
        return set(self._channel_members.get(channel_name, set()))

    async def get_member_count(self, channel_name: str) -> int:
        """Return the number of members in the given channel."""
        members = self._channel_members.get(channel_name)
        if members is None:
            return 0
        return len(members)

    async def get_user_channels(self, user_id: int) -> set[str]:
        """Return the set of channel names the user has joined."""
        return set(self._user_channels.get(user_id, set()))

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        """Remove the user from all channels.  Return set of removed channel names."""
        channels = self._user_channels.pop(user_id, set())
        for channel_name in channels:
            members = self._channel_members.get(channel_name)
            if members is not None:
                members.discard(user_id)
                if not members:
                    del self._channel_members[channel_name]
        return set(channels)

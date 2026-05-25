"""InMemoryChannelRepository — dict-based channel repository for testing."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.channel import ChannelType

if TYPE_CHECKING:
    from osu_server.domain.channel import Channel


class InMemoryChannelRepository:
    """In-memory implementation of the ChannelRepository Protocol.

    Uses plain dicts for storage with auto-incrementing id.
    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._channels_by_id: dict[int, Channel] = {}
        self._id_by_name: dict[str, int] = {}
        self._next_id: int = 1

    async def create(self, channel: Channel) -> Channel:
        """Persist a new channel with an auto-generated id.

        Raises ``ValueError`` if ``name`` already exists.
        """
        if channel.name in self._id_by_name:
            msg = f"channel name already exists: {channel.name}"
            raise ValueError(msg)

        created = replace(channel, id=self._next_id)
        self._next_id += 1

        self._channels_by_id[created.id] = created
        self._id_by_name[created.name] = created.id

        return created

    async def get_by_name(self, name: str) -> Channel | None:
        """Return the channel with *name*, or ``None`` if not found."""
        channel_id = self._id_by_name.get(name)
        if channel_id is None:
            return None
        return self._channels_by_id.get(channel_id)

    async def get_all(self) -> list[Channel]:
        """Return all PUBLIC channels."""
        return [
            ch for ch in self._channels_by_id.values() if ch.channel_type == ChannelType.PUBLIC
        ]

    async def get_auto_join(self) -> list[Channel]:
        """Return all channels with ``auto_join=True``."""
        return [ch for ch in self._channels_by_id.values() if ch.auto_join]

    async def update(self, channel: Channel) -> Channel:
        """Update an existing channel and return the updated entity.

        Raises ``ValueError`` if the channel does not exist.
        """
        if channel.id not in self._channels_by_id:
            msg = f"channel not found: id={channel.id}"
            raise ValueError(msg)

        old = self._channels_by_id[channel.id]

        # If name changed, update the name index
        if old.name != channel.name:
            if channel.name in self._id_by_name:
                msg = f"channel name already exists: {channel.name}"
                raise ValueError(msg)
            del self._id_by_name[old.name]
            self._id_by_name[channel.name] = channel.id

        self._channels_by_id[channel.id] = channel

        return channel

    async def delete(self, channel_id: int) -> None:
        """Delete the channel with *channel_id*.  No-op if not found."""
        channel = self._channels_by_id.pop(channel_id, None)
        if channel is not None:
            _ = self._id_by_name.pop(channel.name, None)

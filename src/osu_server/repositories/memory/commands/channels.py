"""In-memory command-side channel repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryChannelCommandRepository:
    """Channel command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, channel: Channel) -> Channel:
        if channel.name in self._state.channel_id_by_name:
            msg = f"channel name already exists: {channel.name}"
            raise ValueError(msg)

        created = replace(channel, id=self._state.next_channel_id)
        self._state.next_channel_id += 1
        self._state.channels_by_id[created.id] = created
        self._state.channel_id_by_name[created.name] = created.id
        return created

    async def get_by_name(self, name: str) -> Channel | None:
        channel_id = self._state.channel_id_by_name.get(name)
        if channel_id is None:
            return None
        return self._state.channels_by_id.get(channel_id)

    async def update(self, channel: Channel) -> Channel:
        existing = self._state.channels_by_id.get(channel.id)
        if existing is None:
            msg = f"channel not found: id={channel.id}"
            raise ValueError(msg)

        if existing.name != channel.name:
            if channel.name in self._state.channel_id_by_name:
                msg = f"channel name already exists: {channel.name}"
                raise ValueError(msg)
            _ = self._state.channel_id_by_name.pop(existing.name, None)
            self._state.channel_id_by_name[channel.name] = channel.id

        self._state.channels_by_id[channel.id] = channel
        return channel

    async def delete(self, channel_id: int) -> None:
        channel = self._state.channels_by_id.pop(channel_id, None)
        if channel is None:
            return
        _ = self._state.channel_id_by_name.pop(channel.name, None)
        _ = self._state.channel_overrides_by_channel_id.pop(channel_id, None)

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        return list(self._state.channel_overrides_by_channel_id.get(channel_id, []))

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        return {
            channel_id: list(self._state.channel_overrides_by_channel_id.get(channel_id, []))
            for channel_id in channel_ids
        }

    def seed_override(self, override: ChannelRoleOverride) -> None:
        """Seed a channel override for command-side ACL checks."""
        self._state.channel_overrides_by_channel_id.setdefault(override.channel_id, []).append(
            override
        )

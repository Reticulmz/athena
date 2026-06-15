"""In-memory query-side channel repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.chat.channels import ChannelType

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryChannelQueryRepository:
    """Read-only channel repository that reads committed memory state."""

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_by_name(self, name: str) -> Channel | None:
        state = self._factory.snapshot()
        channel_id = state.channel_id_by_name.get(name)
        if channel_id is None:
            return None
        return state.channels_by_id.get(channel_id)

    async def get_all(self) -> list[Channel]:
        state = self._factory.snapshot()
        return [
            channel
            for channel in state.channels_by_id.values()
            if channel.channel_type is ChannelType.PUBLIC
        ]

    async def get_auto_join(self) -> list[Channel]:
        state = self._factory.snapshot()
        return [channel for channel in state.channels_by_id.values() if channel.auto_join]

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        state = self._factory.snapshot()
        return list(state.channel_overrides_by_channel_id.get(channel_id, []))

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        state = self._factory.snapshot()
        return {
            channel_id: list(state.channel_overrides_by_channel_id.get(channel_id, []))
            for channel_id in channel_ids
        }

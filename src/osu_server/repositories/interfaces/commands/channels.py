"""Command-side channel repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride


class ChannelCommandRepository(Protocol):
    """Mutation and consistency-check port for channels."""

    async def create(self, channel: Channel) -> Channel:
        """Persist a new channel and return it with repository-assigned identity."""
        ...

    async def get_by_name(self, name: str) -> Channel | None:
        """Return a channel by name for uniqueness and ACL checks."""
        ...

    async def update(self, channel: Channel) -> Channel:
        """Persist channel changes."""
        ...

    async def delete(self, channel_id: int) -> None:
        """Delete a channel by identifier."""
        ...

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """Return role overrides for a channel command decision."""
        ...

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """Return role overrides keyed by channel id for command decisions."""
        ...

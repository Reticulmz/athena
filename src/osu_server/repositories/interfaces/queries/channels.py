"""Query-side channel repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel, ChannelRoleOverride


class ChannelQueryRepository(Protocol):
    """Read-only channel access for display and compatibility workflows."""

    async def get_by_name(self, name: str) -> Channel | None:
        """Return the channel with the name."""
        ...

    async def get_all(self) -> list[Channel]:
        """Return all public channels."""
        ...

    async def get_auto_join(self) -> list[Channel]:
        """Return auto-join channels."""
        ...

    async def get_overrides_for_channel(self, channel_id: int) -> list[ChannelRoleOverride]:
        """Return role overrides for one channel."""
        ...

    async def get_overrides_for_channels(
        self, channel_ids: list[int]
    ) -> dict[int, list[ChannelRoleOverride]]:
        """Return role overrides keyed by channel id."""
        ...

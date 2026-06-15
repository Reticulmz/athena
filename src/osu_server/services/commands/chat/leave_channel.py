"""Leave chat channel command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class LeaveChannelCommand:
    """Command to leave a channel."""

    user_id: int
    channel_name: str


class LeaveChannelUseCase:
    """Remove a user from a channel's volatile membership state."""

    def __init__(self, *, channel_state: ChannelStateStore) -> None:
        self._channel_state: ChannelStateStore = channel_state

    async def execute(self, command: LeaveChannelCommand) -> None:
        await self._channel_state.remove_member(command.channel_name, command.user_id)
        logger.info("leave", user_id=command.user_id, channel=command.channel_name)

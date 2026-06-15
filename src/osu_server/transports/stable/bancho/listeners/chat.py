"""Chat local listeners - best-effort disconnect cleanup.

設計: ChatListeners セクション (channel-system design.md)
要件: 6.1, 6.2, 6.5, 12.1, 12.2, 12.3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.listeners.base import ListenerGroup, listens

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )


class ChatListeners(ListenerGroup):
    """Local listener for best-effort channel membership cleanup.

    Chat history persistence is Durable Work and is not triggered here.
    """

    _channel_state: ChannelStateStore

    def __init__(
        self,
        *,
        channel_state: ChannelStateStore,
    ) -> None:
        self._channel_state = channel_state

    @listens(UserDisconnected)
    async def on_user_disconnected(self, event: UserDisconnected) -> None:
        """チャンネルステートから切断ユーザーを全チャンネル除去。"""
        _ = await self._channel_state.remove_user_from_all(event.user_id)

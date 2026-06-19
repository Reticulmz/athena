"""chat の local listener と切断時 cleanup。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.listeners.base import ListenerGroup, listens

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )


class ChatListeners(ListenerGroup):
    """切断 event を channel state cleanup に適応する listener。

    chat history persistence は durable work 側の責務であり、この listener では
    process-local な membership cleanup だけを best-effort で実行する。
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

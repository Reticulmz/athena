"""chatのlocal event listenerとdisconnect時channel cleanupを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.listeners.base import ListenerGroup, listens

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )


class ChatListeners(ListenerGroup):
    """disconnect eventをchannel state cleanupへ適応するlistenerを提供する.

    Attributes:
        _channel_state (ChannelStateStore): process-local channel membershipを管理するstore.

    Notes:
        chat historyのdurable persistenceはこのlistenerの責務外である.
    """

    _channel_state: ChannelStateStore

    def __init__(
        self,
        *,
        channel_state: ChannelStateStore,
    ) -> None:
        """Channel state cleanup依存を初期化する.

        Args:
            channel_state (ChannelStateStore): disconnect userをchannelから除去するstore.
        """
        self._channel_state = channel_state

    @listens(UserDisconnected)
    async def on_user_disconnected(self, event: UserDisconnected) -> None:
        """切断userを全channelのprocess-local membershipから除去する.

        Args:
            event (UserDisconnected): 除去対象userのdisconnect domain event.

        Returns:
            None: channel cleanupを実行し,呼び出し側へ値を返さずに完了する.
        """
        _ = await self._channel_state.remove_user_from_all(event.user_id)

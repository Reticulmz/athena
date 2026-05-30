"""ChatListeners — メッセージ永続化ジョブ enqueue + 切断時チャンネル掃除。

ChannelMessageSent / PrivateMessageSent イベントで taskiq ジョブを
enqueue し、UserDisconnected イベントで全チャンネルからメンバーを除去する。

設計: ChatListeners セクション (channel-system design.md)
要件: 6.1, 6.2, 6.5, 12.1, 12.2, 12.3
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent
from osu_server.domain.users.events import UserDisconnected
from osu_server.transports.bancho.listeners.base import ListenerGroup, listens

if TYPE_CHECKING:
    from taskiq import AsyncBroker

    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )


class ChatListeners(ListenerGroup):
    """ドメインイベントリスナー: メッセージ永続化 enqueue + 切断掃除。

    - on_channel_message_sent: persist_channel_message ジョブを enqueue
    - on_private_message_sent: persist_private_message ジョブを enqueue
    - on_user_disconnected: 全チャンネルからメンバーを除去
    """

    _broker: AsyncBroker
    _channel_state: ChannelStateStore

    def __init__(
        self,
        *,
        broker: AsyncBroker,
        channel_state: ChannelStateStore,
    ) -> None:
        self._broker = broker
        self._channel_state = channel_state

    @listens(ChannelMessageSent)
    async def on_channel_message_sent(self, event: ChannelMessageSent) -> None:
        """persist_channel_message ジョブを Valkey キューに enqueue。"""
        task = self._broker.find_task("persist_channel_message")
        if task is not None:
            _ = await task.kiq(event.channel_name, event.sender_name, event.content)

    @listens(PrivateMessageSent)
    async def on_private_message_sent(self, event: PrivateMessageSent) -> None:
        """persist_private_message ジョブを Valkey キューに enqueue。"""
        task = self._broker.find_task("persist_private_message")
        if task is not None:
            _ = await task.kiq(event.sender_id, event.target_id, event.content)

    @listens(UserDisconnected)
    async def on_user_disconnected(self, event: UserDisconnected) -> None:
        """チャンネルステートから切断ユーザーを全チャンネル除去。"""
        _ = await self._channel_state.remove_user_from_all(event.user_id)

"""ChatHandlers — C2S パケットハンドラ 4種。

handle_send_message, handle_send_private_message, handle_join_channel,
handle_leave_channel を @handles デコレータで実装する。

設計: ChatHandlers セクション (channel-system design.md)
要件: 3.1, 3.3, 4.1, 5.1
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog
from caterpillar.model import unpack

from osu_server.domain.chat import (
    ChannelChatAuthorization,
    ChannelChatDestination,
    ChatSender,
    PrivateChatDestination,
    SendChannelMessageInput,
    SendPrivateMessageInput,
)
from osu_server.transports.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.types import BanchoString, Message

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.services.channel_service import ChannelService
    from osu_server.services.chat_service import ChatService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ChatHandlers(HandlerGroup):
    """C2S パケットハンドラ 4種。

    各ハンドラ: Caterpillar でペイロードをパース → SessionStore から
    username/privileges 取得 → ChatService or ChannelService に委譲。
    """

    _chat_service: ChatService
    _channel_service: ChannelService
    _session_store: SessionStore

    def __init__(
        self,
        *,
        chat_service: ChatService,
        channel_service: ChannelService,
        session_store: SessionStore,
    ) -> None:
        self._chat_service = chat_service
        self._channel_service = channel_service
        self._session_store = session_store

    @handles(ClientPacketID.SEND_MESSAGE)
    async def handle_send_message(self, payload: bytes, user_id: int) -> None:
        """SEND_MESSAGE (1) — チャンネルメッセージ送信。"""
        msg = unpack(Message, payload)
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        _ = await self._chat_service.send_channel_message(
            SendChannelMessageInput(
                sender=ChatSender(user_id=user_id, username=session.username),
                destination=ChannelChatDestination(name=msg.target),
                content=msg.content,
                authorization=ChannelChatAuthorization(
                    privileges=session.privileges,
                    role_ids=(),
                ),
            )
        )

    @handles(ClientPacketID.SEND_PRIVATE_MESSAGE)
    async def handle_send_private_message(self, payload: bytes, user_id: int) -> None:
        """SEND_PRIVATE_MESSAGE (25) — PM 送信。"""
        msg = unpack(Message, payload)
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        _ = await self._chat_service.send_private_message(
            SendPrivateMessageInput(
                sender=ChatSender(user_id=user_id, username=session.username),
                destination=PrivateChatDestination(username=msg.target),
                content=msg.content,
            )
        )

    @handles(ClientPacketID.JOIN_CHANNEL)
    async def handle_join_channel(self, payload: bytes, user_id: int) -> None:
        """JOIN_CHANNEL (63) — チャンネル参加。"""
        channel_name = cast("str", unpack(BanchoString, payload))
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        _ = await self._channel_service.join(
            user_id=user_id,
            user_privileges=session.privileges,
            user_role_ids=[],
            channel_name=channel_name,
        )

    @handles(ClientPacketID.LEAVE_CHANNEL)
    async def handle_leave_channel(self, payload: bytes, user_id: int) -> None:
        """LEAVE_CHANNEL (78) — チャンネル離脱。"""
        channel_name = cast("str", unpack(BanchoString, payload))
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        await self._channel_service.leave(
            user_id=user_id,
            channel_name=channel_name,
        )

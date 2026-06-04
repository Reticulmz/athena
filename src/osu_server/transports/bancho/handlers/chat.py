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
    ChannelChatDestination,
    ChatAuthorization,
    ChatSender,
    PrivateChatDestination,
    SendChannelMessageInput,
    SendPrivateMessageInput,
)
from osu_server.domain.system_user import BANCHO_BOT_IDENTITY
from osu_server.transports.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.s2c.chat import (
    channel_join_success,
    channel_revoked,
    send_message,
)
from osu_server.transports.bancho.protocol.types import BanchoString, Message

# Minimum wire size of a Message: 3 empty BanchoStrings (1 byte each) + int32 sender_id (4 bytes)
_MIN_MESSAGE_SIZE: int = 7

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.services.channel_service import ChannelService
    from osu_server.services.chat_service import ChatService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ChatHandlers(HandlerGroup):
    """C2S パケットハンドラ 4種。

    各ハンドラ: Caterpillar でペイロードをパース → SessionStore から
    username/privileges 取得 → ChatService or ChannelService に委譲し、
    S2C パケットを PacketQueue に enqueue する。
    """

    _chat_service: ChatService
    _channel_service: ChannelService
    _session_store: SessionStore
    _packet_queue: PacketQueue

    def __init__(
        self,
        *,
        chat_service: ChatService,
        channel_service: ChannelService,
        session_store: SessionStore,
        packet_queue: PacketQueue,
    ) -> None:
        self._chat_service = chat_service
        self._channel_service = channel_service
        self._session_store = session_store
        self._packet_queue = packet_queue

    @handles(ClientPacketID.SEND_MESSAGE)
    async def handle_send_message(self, payload: bytes, user_id: int) -> None:
        """SEND_MESSAGE (1) — チャンネルメッセージ送信。"""
        if len(payload) < _MIN_MESSAGE_SIZE:
            logger.warning(
                "c2s_payload_too_small",
                packet="SEND_MESSAGE",
                payload_size=len(payload),
                min_expected=_MIN_MESSAGE_SIZE,
            )
            return
        msg = unpack(Message, payload)
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        result = await self._chat_service.send_channel_message(
            SendChannelMessageInput(
                sender=ChatSender(user_id=user_id, username=session.username),
                destination=ChannelChatDestination(name=msg.target),
                content=msg.content,
                authorization=ChatAuthorization(
                    privileges=session.privileges,
                    role_ids=session.role_ids,
                ),
            )
        )
        if result is None or result.delivered_to is None:
            return

        message_packet = send_message(
            sender=session.username,
            content=result.content,
            target=msg.target,
            sender_id=user_id,
        )
        channel_command_packets: list[bytes] = []
        sender_command_packets: list[bytes] = []
        for cr in result.command_responses:
            bot = BANCHO_BOT_IDENTITY
            packet = send_message(
                sender=bot.username,
                content=cr.content,
                target=cr.target,
                sender_id=bot.user_id,
            )
            if cr.target.startswith("#"):
                channel_command_packets.append(packet)
                continue
            sender_command_packets.append(packet)

        channel_packets = (message_packet, *channel_command_packets)
        for target_id in result.delivered_to:
            await self._packet_queue.enqueue(target_id, *channel_packets)

        if channel_command_packets and user_id not in result.delivered_to:
            await self._packet_queue.enqueue(user_id, *channel_command_packets)

        if sender_command_packets:
            await self._packet_queue.enqueue(user_id, *sender_command_packets)

    @handles(ClientPacketID.SEND_PRIVATE_MESSAGE)
    async def handle_send_private_message(self, payload: bytes, user_id: int) -> None:
        """SEND_PRIVATE_MESSAGE (25) — PM 送信。"""
        if len(payload) < _MIN_MESSAGE_SIZE:
            logger.warning(
                "c2s_payload_too_small",
                packet="SEND_PRIVATE_MESSAGE",
                payload_size=len(payload),
                min_expected=_MIN_MESSAGE_SIZE,
            )
            return
        msg = unpack(Message, payload)
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        result = await self._chat_service.send_private_message(
            SendPrivateMessageInput(
                sender=ChatSender(user_id=user_id, username=session.username),
                destination=PrivateChatDestination(username=msg.target),
                content=msg.content,
                authorization=ChatAuthorization(
                    privileges=session.privileges,
                    role_ids=session.role_ids,
                ),
            )
        )
        if result is None:
            return

        if result.target_id is not None and result.is_online:
            await self._packet_queue.enqueue(
                result.target_id,
                send_message(
                    sender=session.username,
                    content=result.content,
                    target=msg.target,
                    sender_id=user_id,
                ),
            )

        for cr in result.command_responses:
            bot = BANCHO_BOT_IDENTITY
            await self._packet_queue.enqueue(
                user_id,
                send_message(
                    sender=bot.username,
                    content=cr.content,
                    target=cr.target,
                    sender_id=bot.user_id,
                ),
            )

    @handles(ClientPacketID.JOIN_CHANNEL)
    async def handle_join_channel(self, payload: bytes, user_id: int) -> None:
        """JOIN_CHANNEL (63) — チャンネル参加。"""
        channel_name = cast("str", unpack(BanchoString, payload))
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        joined = await self._channel_service.join(
            user_id=user_id,
            user_privileges=session.privileges,
            user_role_ids=list(session.role_ids),
            channel_name=channel_name,
        )
        if joined:
            await self._packet_queue.enqueue(
                user_id, channel_join_success(channel_name=channel_name)
            )
            return

        await self._packet_queue.enqueue(user_id, channel_revoked(channel_name=channel_name))

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
        await self._packet_queue.enqueue(user_id, channel_revoked(channel_name=channel_name))

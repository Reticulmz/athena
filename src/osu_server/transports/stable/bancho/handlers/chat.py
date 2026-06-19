"""stable bancho chat C2S パケットを chat command に適応する。

handle_send_message, handle_send_private_message, handle_join_channel,
handle_leave_channel を @handles デコレータで実装する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat import (
    ChannelChatDestination,
    ChatAuthorization,
    ChatSender,
    PrivateChatDestination,
    PrivateMessageDeliveryStatus,
    SendChannelMessageInput,
    SendPrivateMessageInput,
)
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.services.commands.chat import (
    JoinChannelCommand,
    LeaveChannelCommand,
    SendChannelMessageCommand,
    SendPrivateMessageCommand,
)
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.protocol.c2s import (
    parse_channel_name_payload,
    parse_message_payload,
)
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.s2c.chat import (
    channel_join_success,
    channel_revoked,
    send_message,
    user_dm_blocked,
)

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.repositories.interfaces.session_store import UserSessionLookup
    from osu_server.services.commands.chat import (
        JoinChannelUseCase,
        LeaveChannelUseCase,
        SendChannelMessageUseCase,
        SendPrivateMessageUseCase,
    )
    from osu_server.transports.stable.bancho.protocol.types import Message

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ChatHandlers(HandlerGroup):
    """chat C2S packet の transport adapter。

    各 handler は Caterpillar で payload を parse し、active session から
    sender context を補って chat command に委譲する。command result は
    stable S2C packet に戻して PacketQueue へ enqueue する。
    """

    _send_channel_message: SendChannelMessageUseCase
    _send_private_message: SendPrivateMessageUseCase
    _join_channel: JoinChannelUseCase
    _leave_channel: LeaveChannelUseCase
    _session_store: UserSessionLookup
    _packet_queue: PacketQueue

    def __init__(
        self,
        *,
        send_channel_message: SendChannelMessageUseCase,
        send_private_message: SendPrivateMessageUseCase,
        join_channel: JoinChannelUseCase,
        leave_channel: LeaveChannelUseCase,
        session_store: UserSessionLookup,
        packet_queue: PacketQueue,
    ) -> None:
        self._send_channel_message = send_channel_message
        self._send_private_message = send_private_message
        self._join_channel = join_channel
        self._leave_channel = leave_channel
        self._session_store = session_store
        self._packet_queue = packet_queue

    @handles(ClientPacketID.SEND_MESSAGE)
    async def handle_send_message(self, payload: bytes, user_id: int) -> None:
        """SEND_MESSAGE (1) — チャンネルメッセージ送信。"""
        msg = _parse_message(payload, "SEND_MESSAGE")
        if msg is None:
            return
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        command_result = await self._send_channel_message.execute(
            SendChannelMessageCommand(
                message=SendChannelMessageInput(
                    sender=ChatSender(user_id=user_id, username=session.username),
                    destination=ChannelChatDestination(name=msg.target),
                    content=msg.content,
                    authorization=ChatAuthorization(
                        privileges=session.privileges,
                        role_ids=session.role_ids,
                    ),
                )
            )
        )
        result = command_result.result
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
        msg = _parse_message(payload, "SEND_PRIVATE_MESSAGE")
        if msg is None:
            return
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        command_result = await self._send_private_message.execute(
            SendPrivateMessageCommand(
                message=SendPrivateMessageInput(
                    sender=ChatSender(user_id=user_id, username=session.username),
                    destination=PrivateChatDestination(username=msg.target),
                    content=msg.content,
                    authorization=ChatAuthorization(
                        privileges=session.privileges,
                        role_ids=session.role_ids,
                    ),
                )
            )
        )
        result = command_result.result
        if result is None:
            return

        if result.delivery_status is PrivateMessageDeliveryStatus.BLOCKED_BY_FRIEND_ONLY:
            await self._packet_queue.enqueue(user_id, user_dm_blocked(target=msg.target))
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
        channel_name = _parse_channel_name(payload, "JOIN_CHANNEL")
        if channel_name is None:
            return
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        result = await self._join_channel.execute(
            JoinChannelCommand(
                user_id=user_id,
                user_privileges=session.privileges,
                user_role_ids=session.role_ids,
                channel_name=channel_name,
            )
        )
        if result.joined:
            await self._packet_queue.enqueue(
                user_id, channel_join_success(channel_name=channel_name)
            )
            return

        await self._packet_queue.enqueue(user_id, channel_revoked(channel_name=channel_name))

    @handles(ClientPacketID.LEAVE_CHANNEL)
    async def handle_leave_channel(self, payload: bytes, user_id: int) -> None:
        """LEAVE_CHANNEL (78) — チャンネル離脱。"""
        channel_name = _parse_channel_name(payload, "LEAVE_CHANNEL")
        if channel_name is None:
            return
        session = await self._session_store.get_by_user(user_id)
        if session is None:
            return

        await self._leave_channel.execute(
            LeaveChannelCommand(
                user_id=user_id,
                channel_name=channel_name,
            )
        )
        await self._packet_queue.enqueue(user_id, channel_revoked(channel_name=channel_name))


def _parse_message(payload: bytes, packet_name: str) -> Message | None:
    try:
        return parse_message_payload(payload, packet_name=packet_name)
    except PacketReadError as exc:
        logger.warning(
            "c2s_malformed_payload",
            packet=packet_name,
            payload_size=len(payload),
            reason=str(exc),
        )
        return None


def _parse_channel_name(payload: bytes, packet_name: str) -> str | None:
    try:
        return parse_channel_name_payload(payload, packet_name=packet_name)
    except PacketReadError as exc:
        logger.warning(
            "c2s_malformed_payload",
            packet=packet_name,
            payload_size=len(payload),
            reason=str(exc),
        )
        return None

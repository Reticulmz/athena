"""stable Bancho chat C2S packetをchat commandへ適応する.

channel message,private message,channel参加と離脱をpacket queueへのS2C応答へ変換する.
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
    """chat C2S packetをchat commandとS2C packetへ適応する.

    Attributes:
        _send_channel_message (SendChannelMessageUseCase): channel messageを送信するuse case.
        _send_private_message (SendPrivateMessageUseCase): private messageを送信するuse case.
        _join_channel (JoinChannelUseCase): channel参加を処理するuse case.
        _leave_channel (LeaveChannelUseCase): channel離脱を処理するuse case.
        _session_store (UserSessionLookup): senderのcurrent sessionを取得するstore.
        _packet_queue (PacketQueue): stable S2C packetを対象sessionへenqueueするqueue.

    Notes:
        不正payloadまたは存在しないsessionはcommandを実行せずdropする.
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
        """Chat C2S packetを処理する依存を初期化する.

        Args:
            send_channel_message (SendChannelMessageUseCase): channel送信用のuse case.
            send_private_message (SendPrivateMessageUseCase): private message送信用のuse case.
            join_channel (JoinChannelUseCase): channel参加用のuse case.
            leave_channel (LeaveChannelUseCase): channel離脱用のuse case.
            session_store (UserSessionLookup): sender sessionを参照するstore.
            packet_queue (PacketQueue): S2C packetを配信するqueue.
        """
        self._send_channel_message = send_channel_message
        self._send_private_message = send_private_message
        self._join_channel = join_channel
        self._leave_channel = leave_channel
        self._session_store = session_store
        self._packet_queue = packet_queue

    @handles(ClientPacketID.SEND_MESSAGE)
    async def handle_send_message(self, payload: bytes, user_id: int) -> None:
        """SEND_MESSAGEをchannel message commandとS2C packetへ変換する.

        Args:
            payload (bytes): Messageを含むSEND_MESSAGE packet payload.
            user_id (int): messageを送信した認証済みuserのID.

        Returns:
            None: command結果をchannel recipientとsenderへenqueueして値を返さずに完了する.

        Notes:
            channel向けbot応答はrecipientへ,sender専用bot応答はsenderだけへ配信する.
        """
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
        """SEND_PRIVATE_MESSAGEをprivate message commandとS2C packetへ変換する.

        Args:
            payload (bytes): Messageを含むSEND_PRIVATE_MESSAGE packet payload.
            user_id (int): messageを送信した認証済みuserのID.

        Returns:
            None: delivery結果またはbot応答をenqueueして値を返さずに完了する.

        Notes:
            friend-only DMにより拒否された場合はsenderへuser_dm_blockedを返す.
        """
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
        """JOIN_CHANNELをchannel参加commandとS2C応答へ変換する.

        Args:
            payload (bytes): channel名を含むJOIN_CHANNEL packet payload.
            user_id (int): channelへ参加しようとする認証済みuserのID.

        Returns:
            None: 参加可否に対応するS2C packetをenqueueして値を返さずに完了する.
        """
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
        """LEAVE_CHANNELをchannel離脱commandとS2C応答へ変換する.

        Args:
            payload (bytes): channel名を含むLEAVE_CHANNEL packet payload.
            user_id (int): channelから離脱する認証済みuserのID.

        Returns:
            None: 離脱command後にchannel_revokedをenqueueして値を返さずに完了する.
        """
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
    """Message payloadを安全にparseする.

    Args:
        payload (bytes): CaterpillarでdecodeするC2S packet payload.
        packet_name (str): warning logへ記録するpacket名.

    Returns:
        Message | None: parseしたMessage. payloadが不正な場合はNone.
    """
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
    """channel名payloadを安全にparseする.

    Args:
        payload (bytes): CaterpillarでdecodeするC2S packet payload.
        packet_name (str): warning logへ記録するpacket名.

    Returns:
        str | None: parseしたchannel名. payloadが不正な場合はNone.
    """
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

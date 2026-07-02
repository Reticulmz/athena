"""S2C chat packet builders - send_message, channel_join_success, channel_revoked.

Design ref: S2C Chat Builders in channel-system design.md
"""

from caterpillar.byteorder import LittleEndian
from caterpillar.model import pack
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.types import BanchoStringT, Message
from osu_server.transports.stable.bancho.protocol.writer import write_packet


@cpstruct(order=LittleEndian)
class SendMessagePayload:
    """SEND_MESSAGE payload.

    挙動:
        stable client に配送する chat message を Message wire type として保持する.
    引数:
        message: sender/content/target/sender_id を含む Message.
    戻り値:
        Caterpillar pack 時に Message と同じ byte 列へ encode される.
    例外:
        field 値が wire type の範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    message: Message


@cpstruct(order=LittleEndian)
class UserDmBlockedPayload:
    """USER_DM_BLOCKED payload.

    挙動:
        DM が拒否された target を Message wire type として保持する.
    引数:
        message: 空の sender/content と target, sender_id=0 を含む Message.
    戻り値:
        Caterpillar pack 時に Message と同じ byte 列へ encode される.
    例外:
        field 値が wire type の範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        stable client 互換のため Message 形式を維持する.
    """

    message: Message


@cpstruct(order=LittleEndian)
class ChannelJoinSuccessPayload:
    """CHANNEL_JOIN_SUCCESS payload.

    挙動:
        join に成功した channel name を BanchoString として保持する.
    引数:
        channel_name: stable channel name.
    戻り値:
        Caterpillar pack 時に BanchoString の byte 列へ encode される.
    例外:
        channel_name が encode 不能な場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    channel_name: BanchoStringT


@cpstruct(order=LittleEndian)
class ChannelRevokedPayload:
    """CHANNEL_REVOKED payload.

    挙動:
        revoke された channel name を BanchoString として保持する.
    引数:
        channel_name: stable channel name.
    戻り値:
        Caterpillar pack 時に BanchoString の byte 列へ encode される.
    例外:
        channel_name が encode 不能な場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    channel_name: BanchoStringT


def send_message(*, sender: str, content: str, target: str, sender_id: int) -> bytes:
    """SEND_MESSAGE packet を構築する.

    引数:
        sender: 表示する送信者名.
        content: chat message 本文.
        target: channel name または private message target.
        sender_id: 送信者の stable user id.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        field 値が wire type の範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        外部シグネチャと Message wire format は互換性維持のため変更しない.
    """
    msg = Message(sender=sender, content=content, target=target, sender_id=sender_id)
    payload: bytes = pack(SendMessagePayload(message=msg))
    return write_packet(ServerPacketID.SEND_MESSAGE, payload)


def user_dm_blocked(*, target: str) -> bytes:
    """USER_DM_BLOCKED packet を構築する.

    引数:
        target: DM を拒否した target username.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        target が encode 不能な場合は Caterpillar の pack error を送出する.
    制約:
        stable client 互換のため payload は Message wire format とする.
    """
    msg = Message(sender="", content="", target=target, sender_id=0)
    payload: bytes = pack(UserDmBlockedPayload(message=msg))
    return write_packet(ServerPacketID.USER_DM_BLOCKED, payload)


def channel_join_success(*, channel_name: str) -> bytes:
    """CHANNEL_JOIN_SUCCESS packet を構築する.

    引数:
        channel_name: join に成功した stable channel name.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        channel_name が encode 不能な場合は Caterpillar の pack error を送出する.
    制約:
        payload は BanchoString 1 field の wire format とする.
    """
    payload: bytes = pack(ChannelJoinSuccessPayload(channel_name=channel_name))
    return write_packet(ServerPacketID.CHANNEL_JOIN_SUCCESS, payload)


def channel_revoked(*, channel_name: str) -> bytes:
    """CHANNEL_REVOKED packet を構築する.

    引数:
        channel_name: revoke された stable channel name.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        channel_name が encode 不能な場合は Caterpillar の pack error を送出する.
    制約:
        payload は BanchoString 1 field の wire format とする.
    """
    payload: bytes = pack(ChannelRevokedPayload(channel_name=channel_name))
    return write_packet(ServerPacketID.CHANNEL_REVOKED, payload)

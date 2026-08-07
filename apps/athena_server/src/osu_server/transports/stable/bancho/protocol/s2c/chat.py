"""stable clientへ送るS2C chat packetを構築する."""

from caterpillar.byteorder import LittleEndian
from caterpillar.model import pack
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.types import BanchoStringT, Message
from osu_server.transports.stable.bancho.protocol.writer import write_packet


@cpstruct(order=LittleEndian)
class SendMessagePayload:
    """SEND_MESSAGEのMessage payloadを表す.

    Attributes:
        message (Message): 送信者, 本文, 宛先, 送信者IDを持つchat message.
    """

    message: Message


@cpstruct(order=LittleEndian)
class UserDmBlockedPayload:
    """USER_DM_BLOCKEDのMessage形式payloadを表す.

    Attributes:
        message (Message): 空のsender/content, target, sender_id=0を持つmessage.
    """

    message: Message


@cpstruct(order=LittleEndian)
class ChannelJoinSuccessPayload:
    """CHANNEL_JOIN_SUCCESSのchannel name payloadを表す.

    Attributes:
        channel_name (str): joinに成功したBanchoString stable channel名.
    """

    channel_name: BanchoStringT


@cpstruct(order=LittleEndian)
class ChannelRevokedPayload:
    """CHANNEL_REVOKEDのchannel name payloadを表す.

    Attributes:
        channel_name (str): revokeされたBanchoString stable channel名.
    """

    channel_name: BanchoStringT


def send_message(*, sender: str, content: str, target: str, sender_id: int) -> bytes:
    """SEND_MESSAGE packetを構築する.

    Args:
        sender (str): 表示する送信者名.
        content (str): chat message本文.
        target (str): channel名またはprivate message target.
        sender_id (int): 送信者のstable user ID.

    Returns:
        bytes: 7 byte headerとMessage payloadを含むpacket.
    """
    msg = Message(sender=sender, content=content, target=target, sender_id=sender_id)
    payload: bytes = pack(SendMessagePayload(message=msg))
    return write_packet(ServerPacketID.SEND_MESSAGE, payload)


def user_dm_blocked(*, target: str) -> bytes:
    """USER_DM_BLOCKED packetを構築する.

    Args:
        target (str): DMを拒否したtarget username.

    Returns:
        bytes: 7 byte headerとMessage形式payloadを含むpacket.
    """
    msg = Message(sender="", content="", target=target, sender_id=0)
    payload: bytes = pack(UserDmBlockedPayload(message=msg))
    return write_packet(ServerPacketID.USER_DM_BLOCKED, payload)


def channel_join_success(*, channel_name: str) -> bytes:
    """CHANNEL_JOIN_SUCCESS packetを構築する.

    Args:
        channel_name (str): joinに成功したstable channel名.

    Returns:
        bytes: 7 byte headerとBanchoString payloadを含むpacket.
    """
    payload: bytes = pack(ChannelJoinSuccessPayload(channel_name=channel_name))
    return write_packet(ServerPacketID.CHANNEL_JOIN_SUCCESS, payload)


def channel_revoked(*, channel_name: str) -> bytes:
    """CHANNEL_REVOKED packetを構築する.

    Args:
        channel_name (str): revokeされたstable channel名.

    Returns:
        bytes: 7 byte headerとBanchoString payloadを含むpacket.
    """
    payload: bytes = pack(ChannelRevokedPayload(channel_name=channel_name))
    return write_packet(ServerPacketID.CHANNEL_REVOKED, payload)

"""S2C chat packet builders — send_message, channel_join_success, channel_revoked.

Design ref: S2C Chat Builders in channel-system design.md
"""

from caterpillar.byteorder import LittleEndian
from caterpillar.model import pack

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.types import BanchoString, Message
from osu_server.transports.stable.bancho.protocol.writer import write_packet


def send_message(*, sender: str, content: str, target: str, sender_id: int) -> bytes:
    """ServerPacketID.SEND_MESSAGE (7) — delivers a chat message."""
    msg = Message(sender=sender, content=content, target=target, sender_id=sender_id)
    payload: bytes = pack(msg)
    return write_packet(ServerPacketID.SEND_MESSAGE, payload)


def user_dm_blocked(*, target: str) -> bytes:
    """ServerPacketID.USER_DM_BLOCKED (100) — target rejected a private message."""
    msg = Message(sender="", content="", target=target, sender_id=0)
    payload: bytes = pack(msg)
    return write_packet(ServerPacketID.USER_DM_BLOCKED, payload)


def channel_join_success(*, channel_name: str) -> bytes:
    """ServerPacketID.CHANNEL_JOIN_SUCCESS (64) — confirms channel join."""
    payload: bytes = pack(channel_name, LittleEndian + BanchoString)
    return write_packet(ServerPacketID.CHANNEL_JOIN_SUCCESS, payload)


def channel_revoked(*, channel_name: str) -> bytes:
    """ServerPacketID.CHANNEL_REVOKED (66) — channel leave or access denied."""
    payload: bytes = pack(channel_name, LittleEndian + BanchoString)
    return write_packet(ServerPacketID.CHANNEL_REVOKED, payload)

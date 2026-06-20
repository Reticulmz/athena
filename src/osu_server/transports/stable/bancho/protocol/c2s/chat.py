"""C2S chat packet payloads.

Lekuruu bancho-documentation:
- SendMessage (1): Message
- SendPrivateMessage (25): Message
- JoinChannel (63): String channel name
- LeaveChannel (78): String channel name
"""

from typing import cast

from caterpillar.byteorder import LittleEndian
from caterpillar.model import pack, unpack

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.types import BanchoString, Message

_MIN_MESSAGE_SIZE = 7


def message_payload(
    *,
    sender: str,
    content: str,
    target: str,
    sender_id: int,
) -> bytes:
    """Build a chat Message payload for C2S fixtures."""
    payload: bytes = pack(
        Message(
            sender=sender,
            content=content,
            target=target,
            sender_id=sender_id,
        )
    )
    return payload


def channel_name_payload(channel_name: str) -> bytes:
    """Build a channel-name payload for C2S fixtures."""
    payload: bytes = pack(channel_name, LittleEndian + BanchoString)
    return payload


def parse_message_payload(payload: bytes, *, packet_name: str) -> Message:
    """Parse SEND_MESSAGE / SEND_PRIVATE_MESSAGE payload."""
    if len(payload) < _MIN_MESSAGE_SIZE:
        msg = f"{packet_name} payload must be at least {_MIN_MESSAGE_SIZE} bytes"
        raise PacketReadError(msg)
    try:
        parsed = unpack(Message, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc
    _reject_trailing_bytes(pack(parsed), payload, packet_name=packet_name)
    return parsed


def parse_channel_name_payload(payload: bytes, *, packet_name: str) -> str:
    """Parse JOIN_CHANNEL / LEAVE_CHANNEL channel-name payload."""
    try:
        parsed = cast("str", unpack(BanchoString, payload))
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc
    _reject_trailing_bytes(
        pack(parsed, LittleEndian + BanchoString),
        payload,
        packet_name=packet_name,
    )
    return parsed


def _reject_trailing_bytes(
    canonical_payload: bytes,
    actual_payload: bytes,
    *,
    packet_name: str,
) -> None:
    if canonical_payload == actual_payload:
        return
    msg = f"{packet_name} payload contains trailing or non-canonical bytes"
    raise PacketReadError(msg)

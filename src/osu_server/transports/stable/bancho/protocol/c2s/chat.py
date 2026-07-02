"""C2S chat packet payloads.

Lekuruu bancho-documentation:
- SendMessage (1): Message
- SendPrivateMessage (25): Message
- JoinChannel (63): String channel name
- LeaveChannel (78): String channel name
"""

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import int32
from caterpillar.model import pack, unpack
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.types import BanchoString, BanchoStringT, Message

_COMPAT_EMPTY_STRING_PAYLOAD = b"\x0b\x00"
_MIN_MESSAGE_SIZE = 7


@cpstruct(order=LittleEndian)
class ChatMessagePayload:
    """SEND_MESSAGE / SEND_PRIVATE_MESSAGE の Message payload。"""

    message: Message


@cpstruct(order=LittleEndian)
class ChannelNamePayload:
    """JOIN_CHANNEL / LEAVE_CHANNEL の channel name payload。"""

    channel_name: BanchoStringT


def message_payload(
    *,
    sender: str,
    content: str,
    target: str,
    sender_id: int,
) -> bytes:
    """C2S fixture用のchat Message payloadを組み立てる。"""
    return (
        _stable_client_string_payload(sender)
        + _stable_client_string_payload(content)
        + _stable_client_string_payload(target)
        + pack(sender_id, LittleEndian + int32)
    )


def channel_name_payload(channel_name: str) -> bytes:
    """C2S fixture用のchannel name payloadを組み立てる。"""
    payload: bytes = pack(ChannelNamePayload(channel_name=channel_name))
    return payload


def parse_message_payload(payload: bytes, *, packet_name: str) -> Message:
    """SEND_MESSAGE / SEND_PRIVATE_MESSAGE payloadをパースする。"""
    if len(payload) < _MIN_MESSAGE_SIZE:
        msg = f"{packet_name} payload must be at least {_MIN_MESSAGE_SIZE} bytes"
        raise PacketReadError(msg)
    try:
        parsed = unpack(ChatMessagePayload, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc
    _reject_unknown_payload_variant(
        _message_payload_variants(parsed.message),
        payload,
        packet_name=packet_name,
    )
    return parsed.message


def parse_channel_name_payload(payload: bytes, *, packet_name: str) -> str:
    """JOIN_CHANNEL / LEAVE_CHANNEL channel-name payloadをパースする。"""
    try:
        parsed = unpack(ChannelNamePayload, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc
    _reject_unknown_payload_variant(
        (pack(parsed),),
        payload,
        packet_name=packet_name,
    )
    return parsed.channel_name


def _message_payload_variants(message: Message) -> tuple[bytes, ...]:
    sender_id_payload: bytes = pack(message.sender_id, LittleEndian + int32)
    return tuple(
        sender_payload + content_payload + target_payload + sender_id_payload
        for sender_payload in _string_payload_variants(message.sender)
        for content_payload in _string_payload_variants(message.content)
        for target_payload in _string_payload_variants(message.target)
    )


def _string_payload_variants(value: str) -> tuple[bytes, ...]:
    canonical_payload: bytes = pack(value, LittleEndian + BanchoString)
    if value:
        return (canonical_payload,)
    return (canonical_payload, _COMPAT_EMPTY_STRING_PAYLOAD)


def _stable_client_string_payload(value: str) -> bytes:
    if value:
        return pack(value, LittleEndian + BanchoString)
    return _COMPAT_EMPTY_STRING_PAYLOAD


def _reject_unknown_payload_variant(
    accepted_payloads: tuple[bytes, ...],
    actual_payload: bytes,
    *,
    packet_name: str,
) -> None:
    if actual_payload in accepted_payloads:
        return
    msg = f"{packet_name} payload contains trailing or non-canonical bytes"
    raise PacketReadError(msg)

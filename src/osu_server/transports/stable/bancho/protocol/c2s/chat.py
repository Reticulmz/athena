"""C2S chat packet payloadをstable wire contractに従って扱う."""

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
    """SEND_MESSAGE系packetのMessage payloadを表す.

    Attributes:
        message (Message): 送信者, 本文, 宛先, 送信者IDを持つwire message.
    """

    message: Message


@cpstruct(order=LittleEndian)
class ChannelNamePayload:
    """JOIN_CHANNEL系packetのchannel name payloadを表す.

    Attributes:
        channel_name (str): BanchoStringで符号化するstable channel名.
    """

    channel_name: BanchoStringT


def message_payload(
    *,
    sender: str,
    content: str,
    target: str,
    sender_id: int,
) -> bytes:
    """fixture用のstable互換chat Message payloadを組み立てる.

    Args:
        sender (str): wire messageに入れる送信者名.
        content (str): wire messageに入れる本文.
        target (str): channel名またはprivate messageの宛先.
        sender_id (int): 送信者のsigned int32 user ID.

    Returns:
        bytes: 空文字列のstable互換表現を含むMessage payload.
    """
    return (
        _stable_client_string_payload(sender)
        + _stable_client_string_payload(content)
        + _stable_client_string_payload(target)
        + pack(sender_id, LittleEndian + int32)
    )


def channel_name_payload(channel_name: str) -> bytes:
    """fixture用のchannel name payloadを組み立てる.

    Args:
        channel_name (str): BanchoStringで符号化するchannel名.

    Returns:
        bytes: JOIN_CHANNELまたはLEAVE_CHANNELに渡すpayload.
    """
    payload: bytes = pack(ChannelNamePayload(channel_name=channel_name))
    return payload


def parse_message_payload(payload: bytes, *, packet_name: str) -> Message:
    """SEND_MESSAGE系payloadをMessageへ解析する.

    Args:
        payload (bytes): clientから受け取ったMessage wire bytes.
        packet_name (str): error messageに表示するpacket名.

    Returns:
        Message: canonicalまたは空文字列互換表現として検証済みのmessage.

    Raises:
        PacketReadError: payloadが短い, decodeできない, または非canonicalの場合.
    """
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
    """JOIN_CHANNEL系payloadをchannel名へ解析する.

    Args:
        payload (bytes): clientから受け取ったBanchoString payload.
        packet_name (str): error messageに表示するpacket名.

    Returns:
        str: trailing byteを含まない検証済みchannel名.

    Raises:
        PacketReadError: payloadをdecodeできないかcanonical bytesと一致しない場合.
    """
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
    """messageに許可するstable互換payload表現を列挙する.

    Args:
        message (Message): 表現候補を作るdecode済みmessage.

    Returns:
        tuple[bytes, ...]: 各空文字列にcanonicalまたは互換表現を使ったpayload候補.
    """
    sender_id_payload: bytes = pack(message.sender_id, LittleEndian + int32)
    return tuple(
        sender_payload + content_payload + target_payload + sender_id_payload
        for sender_payload in _string_payload_variants(message.sender)
        for content_payload in _string_payload_variants(message.content)
        for target_payload in _string_payload_variants(message.target)
    )


def _string_payload_variants(value: str) -> tuple[bytes, ...]:
    """文字列に許可するBanchoString payload表現を返す.

    Args:
        value (str): wire表現に変換する文字列.

    Returns:
        tuple[bytes, ...]: 非空文字列ではcanonical表現, 空文字列では互換表現も含む候補.
    """
    canonical_payload: bytes = pack(value, LittleEndian + BanchoString)
    if value:
        return (canonical_payload,)
    return (canonical_payload, _COMPAT_EMPTY_STRING_PAYLOAD)


def _stable_client_string_payload(value: str) -> bytes:
    """Stable client fixture向けに文字列をwire bytesへ変換する.

    Args:
        value (str): wire表現に変換する文字列.

    Returns:
        bytes: 非空文字列はcanonical, 空文字列はstable互換の2 byte表現.
    """
    if value:
        return pack(value, LittleEndian + BanchoString)
    return _COMPAT_EMPTY_STRING_PAYLOAD


def _reject_unknown_payload_variant(
    accepted_payloads: tuple[bytes, ...],
    actual_payload: bytes,
    *,
    packet_name: str,
) -> None:
    """Actual payloadが許可済みのwire variantか検証する.

    Args:
        accepted_payloads (tuple[bytes, ...]): decode済み値から再構成した許可候補.
        actual_payload (bytes): clientから実際に受け取ったpayload.
        packet_name (str): error messageに表示するpacket名.

    Returns:
        None: 許可済みvariantなら値を返さず完了する.

    Raises:
        PacketReadError: trailing bytesまたは未対応のwire表現を含む場合.
    """
    if actual_payload in accepted_payloads:
        return
    msg = f"{packet_name} payload contains trailing or non-canonical bytes"
    raise PacketReadError(msg)

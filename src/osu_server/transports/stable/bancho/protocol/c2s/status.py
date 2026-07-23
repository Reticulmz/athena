"""C2S STATUS_CHANGE payloadをstable wire contractに従って扱う."""

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import int32, uint8
from caterpillar.model import pack, unpack
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.types import BanchoString, StatusUpdate

_COMPAT_EMPTY_STRING_PAYLOAD = b"\x0b\x00"


@cpstruct(order=LittleEndian)
class StatusChangePayload:
    """STATUS_CHANGEのStatusUpdate payloadを表す.

    Attributes:
        status_update (StatusUpdate): player statusを表すwire field群.
    """

    status_update: StatusUpdate


def status_change_payload(status_update: StatusUpdate) -> bytes:
    """fixture用のSTATUS_CHANGE payloadを構築する.

    Args:
        status_update (StatusUpdate): wire順に符号化するplayer status.

    Returns:
        bytes: StatusUpdate 1 fieldで構成したpayload.
    """
    payload: bytes = pack(StatusChangePayload(status_update=status_update))
    return payload


def parse_status_change_payload(payload: bytes) -> StatusUpdate:
    """stable互換の空文字表現を含むSTATUS_CHANGE payloadを解析する.

    Args:
        payload (bytes): clientから受け取ったStatusUpdate payload.

    Returns:
        StatusUpdate: canonicalまたは空文字列互換表現として検証済みのstatus.

    Raises:
        PacketReadError: payloadをdecodeできないか非canonical bytesを含む場合.
    """
    try:
        parsed = unpack(StatusChangePayload, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc
    if payload not in _status_update_payload_variants(parsed.status_update):
        msg = "STATUS_CHANGE payload contains trailing or non-canonical bytes"
        raise PacketReadError(msg)
    return parsed.status_update


def _status_update_payload_variants(status_update: StatusUpdate) -> tuple[bytes, ...]:
    """Status updateに許可するstable互換payload表現を列挙する.

    Args:
        status_update (StatusUpdate): 表現候補を作るdecode済みstatus.

    Returns:
        tuple[bytes, ...]: 空文字列のcanonicalまたは互換表現を組み合わせた候補.
    """
    status_payload: bytes = pack(status_update.status, LittleEndian + uint8)
    mods_payload: bytes = pack(status_update.mods, LittleEndian + int32)
    play_mode_payload: bytes = pack(status_update.play_mode, LittleEndian + uint8)
    beatmap_id_payload: bytes = pack(status_update.beatmap_id, LittleEndian + int32)
    return tuple(
        status_payload
        + status_text_payload
        + beatmap_md5_payload
        + mods_payload
        + play_mode_payload
        + beatmap_id_payload
        for status_text_payload in _string_payload_variants(status_update.status_text)
        for beatmap_md5_payload in _string_payload_variants(status_update.beatmap_md5)
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

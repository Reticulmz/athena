"""C2S status packet payloads.

Lekuruu bancho-documentation:
- ChangeStatus (0): StatusUpdate
"""

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import int32, uint8
from caterpillar.model import pack, unpack

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.types import BanchoString, StatusUpdate

_COMPAT_EMPTY_STRING_PAYLOAD = b"\x0b\x00"


def status_change_payload(status_update: StatusUpdate) -> bytes:
    """C2S fixture 用の STATUS_CHANGE payload を構築する。"""
    payload: bytes = pack(status_update)
    return payload


def parse_status_change_payload(payload: bytes) -> StatusUpdate:
    """STATUS_CHANGE payload を stable 互換の空文字表現込みで解析する。"""
    try:
        parsed = unpack(StatusUpdate, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc
    if payload not in _status_update_payload_variants(parsed):
        msg = "STATUS_CHANGE payload contains trailing or non-canonical bytes"
        raise PacketReadError(msg)
    return parsed


def _status_update_payload_variants(status_update: StatusUpdate) -> tuple[bytes, ...]:
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
    canonical_payload: bytes = pack(value, LittleEndian + BanchoString)
    if value:
        return (canonical_payload,)
    return (canonical_payload, _COMPAT_EMPTY_STRING_PAYLOAD)

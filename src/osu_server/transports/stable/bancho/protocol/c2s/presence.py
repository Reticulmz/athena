"""Stable presence request C2S payload parsing."""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.fields import int32, uint16
from caterpillar.model import pack, unpack
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

_MAX_PRESENCE_REQUEST_IDS = 256
_PRESENCE_REQUEST_ALL_RESERVED_PAYLOAD_SIZE = 4


@cpstruct(order=LittleEndian)
class PresenceRequestPayload:
    """PRESENCE_REQUEST の user id list payload。"""

    count: Annotated[int, uint16]
    user_ids: Annotated[list[int], int32[this.count]]


@cpstruct(order=LittleEndian)
class PresenceRequestAllReservedPayload:
    """PRESENCE_REQUEST_ALL の互換 reserved int32 payload。"""

    reserved: Annotated[int, int32]


def presence_request_payload(user_ids: list[int]) -> bytes:
    """C2S fixture 用の PRESENCE_REQUEST payload を構築する。"""
    payload: bytes = pack(PresenceRequestPayload(count=len(user_ids), user_ids=user_ids))
    return payload


def parse_presence_request_payload(payload: bytes) -> tuple[int, ...]:
    """PRESENCE_REQUEST payload を検証して user id 順で返す。"""
    try:
        parsed = unpack(PresenceRequestPayload, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc

    canonical_payload: bytes = pack(parsed)
    if canonical_payload != payload:
        msg = "PRESENCE_REQUEST payload contains trailing or non-canonical bytes"
        raise PacketReadError(msg)

    if parsed.count > _MAX_PRESENCE_REQUEST_IDS:
        msg = f"PRESENCE_REQUEST payload may contain at most {_MAX_PRESENCE_REQUEST_IDS} ids"
        raise PacketReadError(msg)

    return tuple(parsed.user_ids)


def parse_presence_request_all_payload(payload: bytes) -> None:
    """PRESENCE_REQUEST_ALL payload を検証する。

    bancho.py reads a reserved i32, while other references document this
    packet as empty. Accept both wire shapes.
    """
    if len(payload) == 0:
        return
    if len(payload) == _PRESENCE_REQUEST_ALL_RESERVED_PAYLOAD_SIZE:
        _ = unpack(PresenceRequestAllReservedPayload, payload)
        return

    msg = "PRESENCE_REQUEST_ALL payload must be empty or a reserved int32"
    raise PacketReadError(msg)


__all__ = [
    "PresenceRequestAllReservedPayload",
    "PresenceRequestPayload",
    "parse_presence_request_all_payload",
    "parse_presence_request_payload",
    "presence_request_payload",
]

"""Stable presence request C2S payload parsing."""

from __future__ import annotations

from caterpillar.model import pack, unpack

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.types import IntList

_MAX_PRESENCE_REQUEST_IDS = 256


def presence_request_payload(user_ids: list[int]) -> bytes:
    """Build a PresenceRequest IntList payload for C2S fixtures."""
    payload: bytes = pack(IntList(count=len(user_ids), values=user_ids))
    return payload


def parse_presence_request_payload(payload: bytes) -> tuple[int, ...]:
    """Parse PRESENCE_REQUEST IntList payload."""
    try:
        parsed = unpack(IntList, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc

    canonical_payload: bytes = pack(parsed)
    if canonical_payload != payload:
        msg = "PRESENCE_REQUEST payload contains trailing or non-canonical bytes"
        raise PacketReadError(msg)

    if parsed.count > _MAX_PRESENCE_REQUEST_IDS:
        msg = f"PRESENCE_REQUEST payload may contain at most {_MAX_PRESENCE_REQUEST_IDS} ids"
        raise PacketReadError(msg)

    return tuple(parsed.values)


def parse_presence_request_all_payload(payload: bytes) -> None:
    """Parse PRESENCE_REQUEST_ALL payload.

    bancho.py reads a reserved i32, while other references document this
    packet as empty. Accept both wire shapes.
    """
    if len(payload) in (0, 4):
        return

    msg = "PRESENCE_REQUEST_ALL payload must be empty or a reserved int32"
    raise PacketReadError(msg)


__all__ = [
    "parse_presence_request_all_payload",
    "parse_presence_request_payload",
    "presence_request_payload",
]

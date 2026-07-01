"""C2S stats request packet payloads."""

from __future__ import annotations

from caterpillar.model import pack, unpack

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.types import IntList

_MAX_STATS_REQUEST_IDS = 256


def stats_request_payload(user_ids: list[int]) -> bytes:
    """STATS_REQUEST fixture 用の IntList payload を構築する."""
    payload: bytes = pack(IntList(count=len(user_ids), values=user_ids))
    return payload


def parse_stats_request_payload(payload: bytes) -> tuple[int, ...]:
    """STATS_REQUEST の IntList payload を検証して user id 順で返す."""
    try:
        parsed = unpack(IntList, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc

    canonical_payload: bytes = pack(parsed)
    if canonical_payload != payload:
        msg = "STATS_REQUEST payload contains trailing or non-canonical bytes"
        raise PacketReadError(msg)

    if parsed.count > _MAX_STATS_REQUEST_IDS:
        msg = f"STATS_REQUEST payload may contain at most {_MAX_STATS_REQUEST_IDS} ids"
        raise PacketReadError(msg)

    return tuple(parsed.values)


__all__ = [
    "parse_stats_request_payload",
    "stats_request_payload",
]

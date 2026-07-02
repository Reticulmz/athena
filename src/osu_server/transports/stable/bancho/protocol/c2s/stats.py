"""C2S stats request packet payloads."""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.fields import int32, uint16
from caterpillar.model import pack, unpack
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

_MAX_STATS_REQUEST_IDS = 256


@cpstruct(order=LittleEndian)
class StatsRequestPayload:
    """STATS_REQUEST の user id list payload。"""

    count: Annotated[int, uint16]
    user_ids: Annotated[list[int], int32[this.count]]


def stats_request_payload(user_ids: list[int]) -> bytes:
    """STATS_REQUEST fixture 用の IntList payload を構築する."""
    payload: bytes = pack(StatsRequestPayload(count=len(user_ids), user_ids=user_ids))
    return payload


def parse_stats_request_payload(payload: bytes) -> tuple[int, ...]:
    """STATS_REQUEST の IntList payload を検証して user id 順で返す."""
    try:
        parsed = unpack(StatsRequestPayload, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc

    canonical_payload: bytes = pack(parsed)
    if canonical_payload != payload:
        msg = "STATS_REQUEST payload contains trailing or non-canonical bytes"
        raise PacketReadError(msg)

    if parsed.count > _MAX_STATS_REQUEST_IDS:
        msg = f"STATS_REQUEST payload may contain at most {_MAX_STATS_REQUEST_IDS} ids"
        raise PacketReadError(msg)

    return tuple(parsed.user_ids)


__all__ = [
    "StatsRequestPayload",
    "parse_stats_request_payload",
    "stats_request_payload",
]

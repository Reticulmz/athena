"""C2S stats request packet payloadを解析および構築する."""

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
    """STATS_REQUESTのuser ID list payloadを表す.

    Attributes:
        count (int): user_idsの件数を表すuint16 wire値.
        user_ids (list[int]): count件のsigned int32 user IDをwire順に保持する一覧.
    """

    count: Annotated[int, uint16]
    user_ids: Annotated[list[int], int32[this.count]]


def stats_request_payload(user_ids: list[int]) -> bytes:
    """fixture用のSTATS_REQUEST IntList payloadを構築する.

    Args:
        user_ids (list[int]): statsを要求するstable user IDの一覧.

    Returns:
        bytes: countとsigned int32 user ID列を連結したpayload.
    """
    payload: bytes = pack(StatsRequestPayload(count=len(user_ids), user_ids=user_ids))
    return payload


def parse_stats_request_payload(payload: bytes) -> tuple[int, ...]:
    """STATS_REQUEST IntList payloadを検証してuser ID順で返す.

    Args:
        payload (bytes): stable clientから受け取ったC2S payload bytes.

    Returns:
        tuple[int, ...]: payloadに含まれるuser IDをwire順に並べたtuple.

    Raises:
        PacketReadError: payloadをdecodeできない, 非canonical, または256件を超える場合.
    """
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

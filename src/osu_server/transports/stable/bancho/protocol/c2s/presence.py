"""stable presence requestのC2S payloadを解析する."""

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
    """PRESENCE_REQUESTのuser ID list payloadを表す.

    Attributes:
        count (int): user_idsの件数を表すuint16 wire値.
        user_ids (list[int]): count件のsigned int32 user IDをwire順に保持する一覧.
    """

    count: Annotated[int, uint16]
    user_ids: Annotated[list[int], int32[this.count]]


@cpstruct(order=LittleEndian)
class PresenceRequestAllReservedPayload:
    """PRESENCE_REQUEST_ALLの互換reserved int32 payloadを表す.

    Attributes:
        reserved (int): semanticsを持たず互換性のためだけに読むsigned int32値.
    """

    reserved: Annotated[int, int32]


def presence_request_payload(user_ids: list[int]) -> bytes:
    """fixture用のPRESENCE_REQUEST payloadを構築する.

    Args:
        user_ids (list[int]): stable clientがpresenceを要求するuser IDの一覧.

    Returns:
        bytes: countとsigned int32 user ID列を連結したpayload.

    Notes:
        件数上限はparse側で検証し, このbuilderは入力順を保ったwire bytesを生成する.
    """
    payload: bytes = pack(PresenceRequestPayload(count=len(user_ids), user_ids=user_ids))
    return payload


def parse_presence_request_payload(payload: bytes) -> tuple[int, ...]:
    """PRESENCE_REQUEST payloadを検証してuser ID順で返す.

    Args:
        payload (bytes): stable clientから受け取ったC2S payload bytes.

    Returns:
        tuple[int, ...]: payloadに含まれるuser IDをwire順に並べたtuple.

    Raises:
        PacketReadError: payloadが壊れている, 非canonical, または256件を超えるuser IDを含む場合.
    """
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
    """PRESENCE_REQUEST_ALL payloadを検証する.

    Args:
        payload (bytes): stable clientから受け取ったC2S payload bytes.

    Returns:
        None: payloadが許可されたwire shapeなら値を返さず完了する.

    Raises:
        PacketReadError: payloadが空でも互換reserved int32でもない場合.

    Notes:
        参照実装と資料間の互換性のため, empty packetとreserved int32の両方を許容する.
    """
    if len(payload) == 0:
        return
    if len(payload) == _PRESENCE_REQUEST_ALL_RESERVED_PAYLOAD_SIZE:
        try:
            _ = unpack(PresenceRequestAllReservedPayload, payload)
        except Exception as exc:
            raise PacketReadError(str(exc)) from exc
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

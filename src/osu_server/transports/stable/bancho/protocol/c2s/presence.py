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
    """C2S fixture 用の PRESENCE_REQUEST payload を構築する。

    引数:
        user_ids: stable client が presence を要求する user id の一覧。

    戻り値:
        `count + int32[]` の wire 形式で構築した payload。

    制約:
        `user_ids` の件数上限は parse 側で検証する。fixture builder は
        入力順を保持して wire bytes を生成する。
    """
    payload: bytes = pack(PresenceRequestPayload(count=len(user_ids), user_ids=user_ids))
    return payload


def parse_presence_request_payload(payload: bytes) -> tuple[int, ...]:
    """PRESENCE_REQUEST payload を検証して user id 順で返す。

    引数:
        payload: stable client から受け取った C2S payload bytes。

    戻り値:
        payload に含まれる user id を wire 順に並べた tuple。

    例外:
        PacketReadError: payload が壊れている、非 canonical、または 256 件を
            超える user id を含む場合。
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
    """PRESENCE_REQUEST_ALL payload を検証する。

    引数:
        payload: stable client から受け取った C2S payload bytes。

    戻り値:
        なし。payload が許容される wire shape の場合は正常に戻る。

    例外:
        PacketReadError: payload が空でも互換 reserved int32 でもない場合。

    制約:
        参照実装には reserved int32 を読む実装がある一方で、
        他の資料では empty packet とされているため、両方の wire shape を許容する。
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

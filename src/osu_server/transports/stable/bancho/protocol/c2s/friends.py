"""C2S friend packet payloadをstable wire contractに従って扱う."""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import int8, int32
from caterpillar.model import pack, struct, unpack

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

_FRIEND_USER_ID_PAYLOAD_SIZE = 4
_FRIEND_ONLY_DMS_PAYLOAD_SIZE = 1


@struct(order=LittleEndian)
class FriendUserIdPayload:
    """ADD_FRIEND系packetのtarget user ID payloadを表す.

    Attributes:
        user_id (int): signed int32で符号化する対象user ID.
    """

    user_id: Annotated[int, int32]


@struct(order=LittleEndian)
class FriendOnlyDmsPayload:
    """CHANGE_FRIENDONLY_DMSのenabled flag payloadを表す.

    Attributes:
        enabled (int): enabledを表す0または1のsigned int8 wire値.
    """

    enabled: Annotated[int, int8]


def friend_user_id_payload(user_id: int) -> bytes:
    """fixture用のfriend target user payloadを構築する.

    Args:
        user_id (int): ADD_FRIENDまたはREMOVE_FRIENDの対象user ID.

    Returns:
        bytes: signed int32 1 fieldのpayload.
    """
    payload: bytes = pack(FriendUserIdPayload(user_id=user_id))
    return payload


def friend_only_dms_payload(enabled: bool) -> bytes:
    """fixture用のfriend-only DM flag payloadを構築する.

    Args:
        enabled (bool): friend-only DMを有効にする場合はTrue.

    Returns:
        bytes: Trueを1, Falseを0にしたsigned int8 payload.
    """
    payload: bytes = pack(FriendOnlyDmsPayload(enabled=1 if enabled else 0))
    return payload


def parse_friend_user_id_payload(payload: bytes, *, packet_name: str) -> int:
    """Friend target user ID payloadを解析する.

    Args:
        payload (bytes): signed int32 1 fieldである必要があるpayload.
        packet_name (str): error messageに表示するpacket名.

    Returns:
        int: payloadに入っていた対象user ID.

    Raises:
        PacketReadError: payloadのbyte長が4 bytesではない場合.
    """
    _validate_payload_size(
        payload,
        expected_size=_FRIEND_USER_ID_PAYLOAD_SIZE,
        packet_name=packet_name,
    )
    parsed = unpack(FriendUserIdPayload, payload)
    return parsed.user_id


def parse_friend_only_dms_payload(payload: bytes) -> bool:
    """friend-only DM flag payloadをboolへ解析する.

    Args:
        payload (bytes): 0または1のsigned int8を持つpayload.

    Returns:
        bool: wire値が1の場合はTrue, 0の場合はFalse.

    Raises:
        PacketReadError: payloadが1 byteでないかwire値が0または1以外の場合.
    """
    _validate_payload_size(
        payload,
        expected_size=_FRIEND_ONLY_DMS_PAYLOAD_SIZE,
        packet_name="CHANGE_FRIENDONLY_DMS",
    )
    parsed = unpack(FriendOnlyDmsPayload, payload)
    if parsed.enabled not in (0, 1):
        msg = "CHANGE_FRIENDONLY_DMS enabled must be 0 or 1"
        raise PacketReadError(msg)
    return parsed.enabled == 1


def _validate_payload_size(
    payload: bytes,
    *,
    expected_size: int,
    packet_name: str,
) -> None:
    """payloadが期待する固定byte長か検証する.

    Args:
        payload (bytes): 検証するclient payload.
        expected_size (int): 許可するpayload byte長.
        packet_name (str): error messageに表示するpacket名.

    Returns:
        None: byte長が一致すれば値を返さず完了する.

    Raises:
        PacketReadError: payloadのbyte長が期待値と一致しない場合.
    """
    if len(payload) == expected_size:
        return
    msg = f"{packet_name} payload must be {expected_size} bytes, got {len(payload)}"
    raise PacketReadError(msg)

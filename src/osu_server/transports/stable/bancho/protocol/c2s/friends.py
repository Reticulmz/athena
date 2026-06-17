"""C2S friend packet payloads.

Lekuruu bancho-documentation:
- AddFriend (73): sInt UserId
- RemoveFriend (74): sInt UserId
- ChangeFriendonlyDms (99): sInt Enabled (1 or 0)
"""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import int8, int32
from caterpillar.model import pack, struct, unpack

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

_FRIEND_USER_ID_PAYLOAD_SIZE = 4
_FRIEND_ONLY_DMS_PAYLOAD_SIZE = 1


@struct(order=LittleEndian)
class FriendUserIdPayload:
    """ADD_FRIEND / REMOVE_FRIEND payload."""

    user_id: Annotated[int, int32]


@struct(order=LittleEndian)
class FriendOnlyDmsPayload:
    """CHANGE_FRIENDONLY_DMS payload."""

    enabled: Annotated[int, int8]


def friend_user_id_payload(user_id: int) -> bytes:
    """Build a friend target-user payload for C2S fixtures."""
    payload: bytes = pack(FriendUserIdPayload(user_id=user_id))
    return payload


def friend_only_dms_payload(enabled: bool) -> bytes:
    """Build a friend-only DM payload for C2S fixtures."""
    payload: bytes = pack(FriendOnlyDmsPayload(enabled=1 if enabled else 0))
    return payload


def parse_friend_user_id_payload(payload: bytes, *, packet_name: str) -> int:
    """Parse ADD_FRIEND / REMOVE_FRIEND target user ID."""
    _validate_payload_size(
        payload,
        expected_size=_FRIEND_USER_ID_PAYLOAD_SIZE,
        packet_name=packet_name,
    )
    parsed = unpack(FriendUserIdPayload, payload)
    return parsed.user_id


def parse_friend_only_dms_payload(payload: bytes) -> bool:
    """Parse CHANGE_FRIENDONLY_DMS enabled flag."""
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
    if len(payload) == expected_size:
        return
    msg = f"{packet_name} payload must be {expected_size} bytes, got {len(payload)}"
    raise PacketReadError(msg)

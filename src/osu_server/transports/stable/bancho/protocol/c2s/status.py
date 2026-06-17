"""C2S status packet payloads.

Lekuruu bancho-documentation:
- ChangeStatus (0): StatusUpdate
"""

from caterpillar.model import pack, unpack

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.types import StatusUpdate


def status_change_payload(status_update: StatusUpdate) -> bytes:
    """Build a STATUS_CHANGE payload for C2S fixtures."""
    payload: bytes = pack(status_update)
    return payload


def parse_status_change_payload(payload: bytes) -> StatusUpdate:
    """Parse STATUS_CHANGE payload."""
    try:
        parsed = unpack(StatusUpdate, payload)
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc
    if pack(parsed) != payload:
        msg = "STATUS_CHANGE payload contains trailing or non-canonical bytes"
        raise PacketReadError(msg)
    return parsed

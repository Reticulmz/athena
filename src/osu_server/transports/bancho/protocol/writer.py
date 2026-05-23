"""Packet writer — build S2C packets from ServerPacketID and payload.

Design ref: write_packet component in bancho-protocol design.md
Requirements: 4.3
Logging requirements: 6.1, 6.2
"""

import struct

import structlog

from osu_server.transports.bancho.protocol.enums import ServerPacketID

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_HEADER_FMT = struct.Struct("<HBI")

QUIET_S2C_PACKETS: frozenset[ServerPacketID] = frozenset(
    {
        ServerPacketID.PING,
        ServerPacketID.USER_STATS,
        ServerPacketID.USER_PRESENCE,
    }
)


def write_packet(packet_id: ServerPacketID, payload: bytes = b"") -> bytes:
    """Build a complete S2C packet: 7-byte header + payload.

    Compression is always False (unused in modern clients).

    Logging behaviour:
    - Quiet packets (PING, USER_STATS, USER_PRESENCE) → ``logger.debug("s2c_packet", ...)``
    - All other packets → ``logger.info("s2c_packet", ...)``
    """
    header = _HEADER_FMT.pack(packet_id, 0, len(payload))

    log = logger.debug if packet_id in QUIET_S2C_PACKETS else logger.info
    log("s2c_packet", packet=packet_id.name, size=len(payload))

    return header + payload

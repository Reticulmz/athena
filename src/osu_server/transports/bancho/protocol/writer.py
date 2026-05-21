"""Packet writer — build S2C packets from ServerPacketID and payload.

Design ref: write_packet component in bancho-protocol design.md
Requirements: 4.3
"""

import struct

from osu_server.transports.bancho.protocol.enums import ServerPacketID

_HEADER_FMT = struct.Struct("<HBI")


def write_packet(packet_id: ServerPacketID, payload: bytes = b"") -> bytes:
    """Build a complete S2C packet: 7-byte header + payload.

    Compression is always False (unused in modern clients).
    """
    header = _HEADER_FMT.pack(packet_id, 0, len(payload))
    return header + payload

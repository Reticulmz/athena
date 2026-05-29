"""Packet reader — parse C2S packets from a byte stream using Caterpillar Greedy arrays.

Design ref: RawPacket + read_packets component in bancho-protocol design.md
Requirements: 4.1, 4.2, 4.4, 4.5
"""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.fields import Bytes, boolean, uint16, uint32
from caterpillar.model import struct, unpack

from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.errors import PacketReadError
from osu_server.transports.bancho.protocol.header import HEADER_SIZE


@struct(order=LittleEndian)
class RawPacket:
    """Header + variable-length payload as a single Caterpillar struct.

    Used with Greedy array ``RawPacket[...]`` to bulk-parse all packets
    from an HTTP body in one ``unpack()`` call.
    """

    packet_id: Annotated[int, uint16]
    compression: Annotated[bool, boolean]
    content_size: Annotated[int, uint32]
    payload: Annotated[bytes, Bytes(this.content_size)]


def read_packets(data: bytes | bytearray) -> list[tuple[ClientPacketID, bytes]]:
    """Read all C2S packets from *data* using Caterpillar Greedy array.

    Returns a list of ``(ClientPacketID, payload_bytes)`` tuples.
    Unknown packet IDs (not in :class:`ClientPacketID`) are silently skipped.

    Raises :class:`PacketReadError` if the data is malformed (incomplete
    header or insufficient payload).
    """
    if len(data) == 0:
        return []

    if len(data) < HEADER_SIZE:
        msg = f"Incomplete packet header: {len(data)} bytes (need {HEADER_SIZE})"
        raise PacketReadError(msg)

    try:
        raw_packets: list[RawPacket] = unpack(RawPacket[...], bytes(data))  # pyright: ignore[reportAssignmentType, reportInvalidTypeArguments]
    except Exception as exc:
        raise PacketReadError(str(exc)) from exc

    # Post-check: verify all bytes were consumed
    consumed = sum(HEADER_SIZE + rp.content_size for rp in raw_packets)
    if consumed != len(data):
        msg = f"Incomplete packet data: consumed {consumed} of {len(data)} bytes"
        raise PacketReadError(msg)

    result: list[tuple[ClientPacketID, bytes]] = []
    for rp in raw_packets:
        try:
            pid = ClientPacketID(rp.packet_id)
        except ValueError:
            continue  # Unknown packet ID — skip
        result.append((pid, bytes(rp.payload)))

    return result

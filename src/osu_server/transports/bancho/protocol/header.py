"""PacketHeader — bancho binary protocol header (7 bytes, little-endian).

Wire layout (Req 1.1, 1.2):
    Offset 0: PacketID      uint16  (2 bytes)
    Offset 2: Compression   boolean (1 byte)
    Offset 3: ContentSize   uint32  (4 bytes)
    Total:    7 bytes

Design ref: PacketHeader component in bancho-protocol design.md
"""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import boolean, uint16, uint32
from caterpillar.model import struct

HEADER_SIZE: int = 7
"""Fixed byte length of a bancho packet header."""


@struct(order=LittleEndian)
class PacketHeader:
    """Bancho packet header: PacketID + Compression + ContentSize."""

    packet_id: Annotated[int, uint16]
    compression: Annotated[bool, boolean]
    content_size: Annotated[int, uint32]

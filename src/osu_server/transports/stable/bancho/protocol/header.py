"""7 bytes little-endian Bancho packet headerを定義する."""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import boolean, uint16, uint32
from caterpillar.model import struct

HEADER_SIZE: int = 7
"""Fixed byte length of a bancho packet header."""


@struct(order=LittleEndian)
class PacketHeader:
    """Bancho packet headerのwire field群を表す.

    Attributes:
        packet_id (int): uint16のpacket ID.
        compression (bool): 圧縮の有無を表すboolean field.
        content_size (int): uint32のpayload byte長.
    """

    packet_id: Annotated[int, uint16]
    compression: Annotated[bool, boolean]
    content_size: Annotated[int, uint32]

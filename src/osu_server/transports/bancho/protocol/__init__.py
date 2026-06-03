"""bancho binary protocol — public API re-exports."""

from osu_server.transports.bancho.protocol.enums import (
    ClientPacketID,
    ServerPacketID,
)
from osu_server.transports.bancho.protocol.errors import (
    DuplicateHandlerError,
    PacketError,
    PacketReadError,
)
from osu_server.transports.bancho.protocol.header import (
    HEADER_SIZE,
    PacketHeader,
)
from osu_server.transports.bancho.protocol.reader import RawPacket, read_packets
from osu_server.transports.bancho.protocol.types import (
    BanchoString,
    Channel,
    IntList,
    Message,
    StatusUpdate,
)
from osu_server.transports.bancho.protocol.writer import write_packet

PROTOCOL_VERSION = 19

__all__ = [
    "HEADER_SIZE",
    "PROTOCOL_VERSION",
    "BanchoString",
    "Channel",
    "ClientPacketID",
    "DuplicateHandlerError",
    "IntList",
    "Message",
    "PacketError",
    "PacketHeader",
    "PacketReadError",
    "RawPacket",
    "ServerPacketID",
    "StatusUpdate",
    "read_packets",
    "write_packet",
]

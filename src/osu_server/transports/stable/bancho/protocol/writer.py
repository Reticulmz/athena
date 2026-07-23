"""ServerPacketIDとpayloadからS2C packetを構築する."""

import struct

import structlog

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_HEADER_FMT = struct.Struct("<HBI")

QUIET_S2C_PACKETS: frozenset[ServerPacketID] = frozenset(
    {
        ServerPacketID.PING,
        ServerPacketID.USER_STATS,
        ServerPacketID.USER_PRESENCE,
    }
)
"""debug levelで送信eventを記録する頻出S2C packet ID集合を表す."""


def write_packet(packet_id: ServerPacketID, payload: bytes = b"") -> bytes:
    """7 byte headerとpayloadから完全なS2C packetを構築する.

    Args:
        packet_id (ServerPacketID): headerに書き込むS2C packet ID.
        payload (bytes): header直後に連結するpayload. 既定値は空bytes.

    Returns:
        bytes: compression flagをFalseにしたheaderとpayloadの連結bytes.

    Notes:
        PING, USER_STATS, USER_PRESENCEはdebug, それ以外はinfoでs2c_packet eventを記録する.
    """
    header = _HEADER_FMT.pack(packet_id, 0, len(payload))

    log = logger.debug if packet_id in QUIET_S2C_PACKETS else logger.info
    log("s2c_packet", packet=packet_id.name, size=len(payload))

    return header + payload

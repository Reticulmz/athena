"""Caterpillarを使いbyte streamからC2S packetを解析する."""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.fields import Bytes, boolean, uint16, uint32
from caterpillar.model import struct, unpack

from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.header import HEADER_SIZE


@struct(order=LittleEndian)
class RawPacket:
    """headerと可変長payloadを持つCaterpillar structを表す.

    Attributes:
        packet_id (int): uint16のpacket ID.
        compression (bool): headerのcompression flag.
        content_size (int): uint32のpayload byte長.
        payload (bytes): content_size bytesのpacket payload.
    """

    packet_id: Annotated[int, uint16]
    compression: Annotated[bool, boolean]
    content_size: Annotated[int, uint32]
    payload: Annotated[bytes, Bytes(this.content_size)]


def read_packets(data: bytes | bytearray) -> list[tuple[ClientPacketID, bytes]]:
    """C2S packet streamを解析し, 未知IDを除いて返す.

    Args:
        data (bytes | bytearray): 0件以上のheaderとpayloadを連結したHTTP body.

    Returns:
        list[tuple[ClientPacketID, bytes]]: 既知packet IDとpayloadのwire順list.

    Raises:
        PacketReadError: headerまたはpayloadが途中で終わるかCaterpillarがdecodeできない場合.
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

"""RawPacket と read_packets の stable C2S stream parsing contract を検証する.

header と payload の切り出し, 複数 packet, 未知 ID, 不完全 stream を確認する.
"""

import struct as pystruct

import pytest

from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.reader import read_packets


def _build_packet(packet_id: int, payload: bytes = b"") -> bytes:
    """Test 用の raw Bancho packet を header と payload から構築する.

    Args:
        packet_id (int): uint16 header field に入れる packet ID.
        payload (bytes): header の直後に連結する payload bytes.

    Returns:
        bytes: 7 byte little-endian header と payload を連結した raw packet.
    """
    return pystruct.pack("<HBI", packet_id, 0, len(payload)) + payload


class TestReadPacketsSinglePacket:
    """単一 C2S packet stream を read_packets が解析することを検証する."""

    def test_single_known_packet(self) -> None:
        """Payload のない既知 C2S packet が ID と空 payload に解析されることを検証する."""
        data = _build_packet(ClientPacketID.PONG, b"")
        result = read_packets(data)
        assert len(result) == 1
        assert result[0][0] == ClientPacketID.PONG
        assert result[0][1] == b""

    def test_single_packet_with_payload(self) -> None:
        """Payload を持つ既知 C2S packet が ID と original payload に解析されることを検証する."""
        payload = b"\x01\x02\x03\x04"
        data = _build_packet(ClientPacketID.SEND_MESSAGE, payload)
        result = read_packets(data)
        assert len(result) == 1
        assert result[0][0] == ClientPacketID.SEND_MESSAGE
        assert result[0][1] == payload

    def test_returns_client_packet_id_type(self) -> None:
        """既知 packet の parsed ID が ClientPacketID type で返ることを検証する."""
        data = _build_packet(ClientPacketID.EXIT, b"")
        result = read_packets(data)
        assert isinstance(result[0][0], ClientPacketID)


class TestReadPacketsMultiplePackets:
    """連結した複数 C2S packet stream の順次解析を検証する."""

    def test_two_concatenated_packets(self) -> None:
        """2件の空 payload packet が wire順に解析されることを検証する."""
        pkt1 = _build_packet(ClientPacketID.PONG, b"")
        pkt2 = _build_packet(ClientPacketID.EXIT, b"")
        result = read_packets(pkt1 + pkt2)
        assert len(result) == 2
        assert result[0][0] == ClientPacketID.PONG
        assert result[1][0] == ClientPacketID.EXIT

    def test_three_packets_with_varying_payloads(self) -> None:
        """異なる payload size の 3 packet が wire順に解析されることを検証する."""
        pkt1 = _build_packet(ClientPacketID.PONG, b"")
        pkt2 = _build_packet(ClientPacketID.SEND_MESSAGE, b"\xaa\xbb")
        pkt3 = _build_packet(ClientPacketID.EXIT, b"\x01")
        result = read_packets(pkt1 + pkt2 + pkt3)
        assert len(result) == 3
        assert result[1][1] == b"\xaa\xbb"
        assert result[2][1] == b"\x01"


class TestReadPacketsEmptyData:
    """空 byte stream が空の parsed packet list を返すことを検証する."""

    def test_empty_data(self) -> None:
        """空 bytes input が空 list に解析されることを検証する."""
        result = read_packets(b"")
        assert result == []

    def test_empty_bytearray(self) -> None:
        """空 bytearray input が空 list に解析されることを検証する."""
        result = read_packets(bytearray())
        assert result == []


class TestReadPacketsUnknownID:
    """ClientPacketID にない packet ID を read_packets が skip することを検証する."""

    def test_unknown_id_skipped(self) -> None:
        """未知 ID の packet が既知 packet の解析結果から除外されることを検証する."""
        # Use an ID that doesn't exist in ClientPacketID
        unknown = _build_packet(999, b"\x00")
        known = _build_packet(ClientPacketID.PONG, b"")
        result = read_packets(unknown + known)
        assert len(result) == 1
        assert result[0][0] == ClientPacketID.PONG

    def test_all_unknown_returns_empty(self) -> None:
        """すべて未知 ID の stream が空 list に解析されることを検証する."""
        unknown1 = _build_packet(998, b"")
        unknown2 = _build_packet(999, b"\x01\x02")
        result = read_packets(unknown1 + unknown2)
        assert result == []


class TestReadPacketsErrors:
    """不完全な packet header または payload の error handling を検証する."""

    def test_header_incomplete_raises(self) -> None:
        """7 byte 未満の header stream が PacketReadError を送出することを検証する."""
        # Less than 7 bytes
        with pytest.raises(PacketReadError):
            _ = read_packets(b"\x04\x00\x00")

    def test_payload_incomplete_raises(self) -> None:
        """Header 宣言より短い payload stream が PacketReadError を送出することを検証する."""
        # Header says content_size=10 but only 3 bytes follow
        data = pystruct.pack("<HBI", ClientPacketID.PONG, 0, 10) + b"\x01\x02\x03"
        with pytest.raises(PacketReadError):
            _ = read_packets(data)

    def test_single_byte_raises(self) -> None:
        """1 byte だけの stream が PacketReadError を送出することを検証する."""
        with pytest.raises(PacketReadError):
            _ = read_packets(b"\x00")

    def test_six_bytes_raises(self) -> None:
        """6 byte だけの stream が PacketReadError を送出することを検証する."""
        with pytest.raises(PacketReadError):
            _ = read_packets(b"\x00\x00\x00\x00\x00\x00")

# ruff: noqa: PLR2004
# pyright: reportUnknownMemberType=false
"""Tests for RawPacket struct and read_packets function.

Validates:
- Req 4.1: Read C2S packets from byte stream (header + payload extraction)
- Req 4.2: Read multiple concatenated packets sequentially
- Req 4.4: Error on insufficient header bytes (< 7)
- Req 4.5: Error on insufficient payload bytes
"""

import struct as pystruct

import pytest

from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.errors import PacketReadError
from osu_server.transports.bancho.protocol.reader import read_packets


def _build_packet(packet_id: int, payload: bytes = b"") -> bytes:
    """Build a raw packet: header (7 bytes) + payload."""
    return pystruct.pack("<HBI", packet_id, 0, len(payload)) + payload


class TestReadPacketsSinglePacket:
    """Req 4.1: Read a single C2S packet from byte stream."""

    def test_single_known_packet(self) -> None:
        data = _build_packet(ClientPacketID.PONG, b"")
        result = read_packets(data)
        assert len(result) == 1
        assert result[0][0] == ClientPacketID.PONG
        assert result[0][1] == b""

    def test_single_packet_with_payload(self) -> None:
        payload = b"\x01\x02\x03\x04"
        data = _build_packet(ClientPacketID.SEND_MESSAGE, payload)
        result = read_packets(data)
        assert len(result) == 1
        assert result[0][0] == ClientPacketID.SEND_MESSAGE
        assert result[0][1] == payload

    def test_returns_client_packet_id_type(self) -> None:
        data = _build_packet(ClientPacketID.EXIT, b"")
        result = read_packets(data)
        assert isinstance(result[0][0], ClientPacketID)


class TestReadPacketsMultiplePackets:
    """Req 4.2: Read multiple concatenated packets."""

    def test_two_concatenated_packets(self) -> None:
        pkt1 = _build_packet(ClientPacketID.PONG, b"")
        pkt2 = _build_packet(ClientPacketID.EXIT, b"")
        result = read_packets(pkt1 + pkt2)
        assert len(result) == 2
        assert result[0][0] == ClientPacketID.PONG
        assert result[1][0] == ClientPacketID.EXIT

    def test_three_packets_with_varying_payloads(self) -> None:
        pkt1 = _build_packet(ClientPacketID.PONG, b"")
        pkt2 = _build_packet(ClientPacketID.SEND_MESSAGE, b"\xaa\xbb")
        pkt3 = _build_packet(ClientPacketID.EXIT, b"\x01")
        result = read_packets(pkt1 + pkt2 + pkt3)
        assert len(result) == 3
        assert result[1][1] == b"\xaa\xbb"
        assert result[2][1] == b"\x01"


class TestReadPacketsEmptyData:
    """Req 4.1: Empty byte stream returns empty list."""

    def test_empty_data(self) -> None:
        result = read_packets(b"")
        assert result == []

    def test_empty_bytearray(self) -> None:
        result = read_packets(bytearray())
        assert result == []


class TestReadPacketsUnknownID:
    """Req 4.1: Unknown PacketIDs (not in ClientPacketID) are skipped."""

    def test_unknown_id_skipped(self) -> None:
        # Use an ID that doesn't exist in ClientPacketID
        unknown = _build_packet(999, b"\x00")
        known = _build_packet(ClientPacketID.PONG, b"")
        result = read_packets(unknown + known)
        assert len(result) == 1
        assert result[0][0] == ClientPacketID.PONG

    def test_all_unknown_returns_empty(self) -> None:
        unknown1 = _build_packet(998, b"")
        unknown2 = _build_packet(999, b"\x01\x02")
        result = read_packets(unknown1 + unknown2)
        assert result == []


class TestReadPacketsErrors:
    """Req 4.4, 4.5: Errors on insufficient data."""

    def test_header_incomplete_raises(self) -> None:
        # Less than 7 bytes
        with pytest.raises(PacketReadError):
            read_packets(b"\x04\x00\x00")

    def test_payload_incomplete_raises(self) -> None:
        # Header says content_size=10 but only 3 bytes follow
        data = pystruct.pack("<HBI", ClientPacketID.PONG, 0, 10) + b"\x01\x02\x03"
        with pytest.raises(PacketReadError):
            read_packets(data)

    def test_single_byte_raises(self) -> None:
        with pytest.raises(PacketReadError):
            read_packets(b"\x00")

    def test_six_bytes_raises(self) -> None:
        with pytest.raises(PacketReadError):
            read_packets(b"\x00\x00\x00\x00\x00\x00")

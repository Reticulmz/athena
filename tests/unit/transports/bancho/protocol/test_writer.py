# ruff: noqa: PLR2004
"""Tests for write_packet function.

Validates:
- Req 4.3: S2C packet construction (ServerPacketID + payload → header + payload bytes)
"""

import struct as pystruct

from osu_server.transports.bancho.protocol.enums import ServerPacketID
from osu_server.transports.bancho.protocol.writer import write_packet


class TestWritePacketHeader:
    """Req 4.3: write_packet produces correct 7-byte header."""

    def test_header_size(self) -> None:
        result = write_packet(ServerPacketID.PING, b"")
        assert len(result) == 7

    def test_header_packet_id(self) -> None:
        result = write_packet(ServerPacketID.LOGIN_REPLY, b"\x00" * 4)
        packet_id = pystruct.unpack_from("<H", result, 0)[0]
        assert packet_id == ServerPacketID.LOGIN_REPLY

    def test_header_compression_always_false(self) -> None:
        result = write_packet(ServerPacketID.PING, b"")
        assert result[2] == 0  # compression = False

    def test_header_content_size(self) -> None:
        payload = b"\x01\x02\x03\x04"
        result = write_packet(ServerPacketID.PING, payload)
        content_size = pystruct.unpack_from("<I", result, 3)[0]
        assert content_size == 4


class TestWritePacketPayload:
    """Req 4.3: write_packet appends payload after header."""

    def test_empty_payload(self) -> None:
        result = write_packet(ServerPacketID.PING, b"")
        assert result == pystruct.pack("<HBI", ServerPacketID.PING, 0, 0)

    def test_payload_appended(self) -> None:
        payload = b"\xaa\xbb\xcc"
        result = write_packet(ServerPacketID.PING, payload)
        assert result[7:] == payload

    def test_total_length(self) -> None:
        payload = b"\x01" * 10
        result = write_packet(ServerPacketID.PING, payload)
        assert len(result) == 7 + 10


class TestWritePacketKnownBytes:
    """Req 4.3: verify against known protocol byte sequences."""

    def test_login_reply_packet(self) -> None:
        """LoginReply (ID=5) with userId=100 → known byte sequence."""
        payload = pystruct.pack("<i", 100)
        result = write_packet(ServerPacketID.LOGIN_REPLY, payload)
        expected = b"\x05\x00\x00\x04\x00\x00\x00\x64\x00\x00\x00"
        assert result == expected

    def test_channel_info_complete_packet(self) -> None:
        """ChannelInfoComplete (ID=89) with empty payload."""
        result = write_packet(ServerPacketID.CHANNEL_INFO_COMPLETE, b"")
        expected = b"\x59\x00\x00\x00\x00\x00\x00"
        assert result == expected


class TestWritePacketDefaultPayload:
    """Req 4.3: payload defaults to empty bytes."""

    def test_default_payload_is_empty(self) -> None:
        result = write_packet(ServerPacketID.PING)
        assert len(result) == 7
        content_size = pystruct.unpack_from("<I", result, 3)[0]
        assert content_size == 0

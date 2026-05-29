# pyright: reportPrivateUsage=false
"""Tests for write_packet function.

Validates:
- Req 4.3: S2C packet construction (ServerPacketID + payload → header + payload bytes)
- Logging Req 6.1: S2C packet logging with packet name and payload size
- Logging Req 6.2: Noisy packets logged at DEBUG only
"""

import struct as pystruct
from typing import cast

import structlog.testing

from osu_server.transports.bancho.protocol.enums import ServerPacketID
from osu_server.transports.bancho.protocol.writer import (
    _HEADER_FMT,
    QUIET_S2C_PACKETS,
    write_packet,
)


class TestWritePacketHeader:
    """Req 4.3: write_packet produces correct 7-byte header."""

    def test_header_size(self) -> None:
        result = write_packet(ServerPacketID.PING, b"")
        assert len(result) == _HEADER_FMT.size

    def test_header_packet_id(self) -> None:
        result = write_packet(ServerPacketID.LOGIN_REPLY, b"\x00" * 4)
        packet_id = cast("int", pystruct.unpack_from("<H", result, 0)[0])
        assert packet_id == ServerPacketID.LOGIN_REPLY

    def test_header_compression_always_false(self) -> None:
        result = write_packet(ServerPacketID.PING, b"")
        assert result[2] == 0  # compression = False

    def test_header_content_size(self) -> None:
        payload = b"\x01\x02\x03\x04"
        result = write_packet(ServerPacketID.PING, payload)
        content_size = cast("int", pystruct.unpack_from("<I", result, 3)[0])
        assert content_size == len(payload)


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
        assert len(result) == _HEADER_FMT.size
        content_size = cast("int", pystruct.unpack_from("<I", result, 3)[0])
        assert content_size == 0


class TestQuietS2cPackets:
    """QUIET_S2C_PACKETS definition validation."""

    def test_contains_ping(self) -> None:
        assert ServerPacketID.PING in QUIET_S2C_PACKETS

    def test_contains_user_stats(self) -> None:
        assert ServerPacketID.USER_STATS in QUIET_S2C_PACKETS

    def test_contains_user_presence(self) -> None:
        assert ServerPacketID.USER_PRESENCE in QUIET_S2C_PACKETS

    def test_is_frozenset(self) -> None:
        assert isinstance(QUIET_S2C_PACKETS, frozenset)


class TestWritePacketLogging:
    """Logging Req 6.1, 6.2: S2C packet logging."""

    def test_normal_packet_logged_at_info(self) -> None:
        """Req 6.1: Normal (non-quiet) packet logged at INFO with name and size."""
        payload = b"\x01\x02\x03"
        with structlog.testing.capture_logs() as logs:
            _ = write_packet(ServerPacketID.LOGIN_REPLY, payload)

        s2c_logs = [log for log in logs if log["event"] == "s2c_packet"]
        assert len(s2c_logs) == 1
        assert s2c_logs[0]["log_level"] == "info"
        assert s2c_logs[0]["packet"] == "LOGIN_REPLY"
        assert s2c_logs[0]["size"] == len(payload)

    def test_quiet_packet_logged_at_debug(self) -> None:
        """Req 6.2: Quiet packet logged at DEBUG only."""
        with structlog.testing.capture_logs() as logs:
            _ = write_packet(ServerPacketID.PING, b"")

        s2c_logs = [log for log in logs if log["event"] == "s2c_packet"]
        assert len(s2c_logs) == 1
        assert s2c_logs[0]["log_level"] == "debug"
        assert s2c_logs[0]["packet"] == "PING"
        assert s2c_logs[0]["size"] == 0

    def test_all_quiet_packets_logged_at_debug(self) -> None:
        """All packets in QUIET_S2C_PACKETS are logged at debug, not info."""
        for packet_id in QUIET_S2C_PACKETS:
            with structlog.testing.capture_logs() as logs:
                _ = write_packet(packet_id, b"\xaa")

            s2c_logs = [log for log in logs if log["event"] == "s2c_packet"]
            assert len(s2c_logs) == 1, f"{packet_id.name} should produce exactly 1 log"
            assert s2c_logs[0]["log_level"] == "debug", (
                f"{packet_id.name} should be logged at debug"
            )

    def test_size_reflects_payload_not_total(self) -> None:
        """Logged size is the payload size, not the total packet size."""
        payload = b"\x01\x02\x03\x04\x05"
        with structlog.testing.capture_logs() as logs:
            _ = write_packet(ServerPacketID.SEND_MESSAGE, payload)

        s2c_logs = [log for log in logs if log["event"] == "s2c_packet"]
        assert s2c_logs[0]["size"] == len(payload)  # payload size, not header + payload

    def test_logging_does_not_alter_packet_bytes(self) -> None:
        """Logging must not interfere with packet construction."""
        payload = b"\xde\xad"
        with structlog.testing.capture_logs():
            result = write_packet(ServerPacketID.LOGIN_REPLY, payload)

        expected = pystruct.pack("<HBI", ServerPacketID.LOGIN_REPLY, 0, 2) + payload
        assert result == expected

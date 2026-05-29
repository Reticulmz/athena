# ruff: noqa: PLR2004
# pyright: reportUnknownMemberType=false
"""Tests for S2C chat packet builders.

Validates:
- send_message: ServerPacketID.SEND_MESSAGE (7), Message payload
- channel_join_success: ServerPacketID.CHANNEL_JOIN_SUCCESS (64), BanchoString payload
- channel_revoked: ServerPacketID.CHANNEL_REVOKED (66), BanchoString payload
"""

import struct as pystruct
from typing import cast

from osu_server.transports.bancho.protocol.enums import ServerPacketID
from osu_server.transports.bancho.protocol.s2c.chat import (
    channel_join_success,
    channel_revoked,
    send_message,
)


def _extract_packet_id(data: bytes) -> int:
    """Extract the ServerPacketID from the first 2 bytes of a packet."""
    return cast("int", pystruct.unpack_from("<H", data, 0)[0])


def _extract_payload(data: bytes) -> bytes:
    """Extract the payload (after 7-byte header) from a packet."""
    return data[7:]


def _extract_payload_size(data: bytes) -> int:
    """Extract the payload size from header bytes 3-6."""
    return cast("int", pystruct.unpack_from("<I", data, 3)[0])


class TestSendMessage:
    """S2C SEND_MESSAGE (7) — Message struct payload."""

    def test_packet_id(self) -> None:
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        assert _extract_packet_id(pkt) == ServerPacketID.SEND_MESSAGE

    def test_payload_contains_sender(self) -> None:
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        payload = _extract_payload(pkt)
        assert b"TestUser" in payload

    def test_payload_contains_content(self) -> None:
        pkt = send_message(sender="TestUser", content="hello world", target="#osu", sender_id=42)
        payload = _extract_payload(pkt)
        assert b"hello world" in payload

    def test_payload_contains_target(self) -> None:
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        payload = _extract_payload(pkt)
        assert b"#osu" in payload

    def test_payload_contains_sender_id(self) -> None:
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        payload = _extract_payload(pkt)
        # sender_id is the last 4 bytes as int32
        sender_id = cast("int", pystruct.unpack_from("<i", payload, len(payload) - 4)[0])
        assert sender_id == 42

    def test_payload_size_matches_header(self) -> None:
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        declared = _extract_payload_size(pkt)
        actual = len(_extract_payload(pkt))
        assert declared == actual

    def test_returns_bytes(self) -> None:
        result = send_message(sender="A", content="B", target="#c", sender_id=1)
        assert isinstance(result, bytes)


class TestChannelJoinSuccess:
    """S2C CHANNEL_JOIN_SUCCESS (64) — BanchoString payload."""

    def test_packet_id(self) -> None:
        pkt = channel_join_success(channel_name="#osu")
        assert _extract_packet_id(pkt) == ServerPacketID.CHANNEL_JOIN_SUCCESS

    def test_payload_contains_channel_name(self) -> None:
        pkt = channel_join_success(channel_name="#osu")
        payload = _extract_payload(pkt)
        assert b"#osu" in payload

    def test_payload_size_matches_header(self) -> None:
        pkt = channel_join_success(channel_name="#osu")
        declared = _extract_payload_size(pkt)
        actual = len(_extract_payload(pkt))
        assert declared == actual


class TestChannelRevoked:
    """S2C CHANNEL_REVOKED (66) — BanchoString payload."""

    def test_packet_id(self) -> None:
        pkt = channel_revoked(channel_name="#osu")
        assert _extract_packet_id(pkt) == ServerPacketID.CHANNEL_REVOKED

    def test_payload_contains_channel_name(self) -> None:
        pkt = channel_revoked(channel_name="#osu")
        payload = _extract_payload(pkt)
        assert b"#osu" in payload

    def test_payload_size_matches_header(self) -> None:
        pkt = channel_revoked(channel_name="#osu")
        declared = _extract_payload_size(pkt)
        actual = len(_extract_payload(pkt))
        assert declared == actual

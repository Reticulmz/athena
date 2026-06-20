"""Tests for stable C2S chat packet payloads."""

import pytest

from osu_server.transports.stable.bancho.protocol.c2s import (
    channel_name_payload,
    message_payload,
    parse_channel_name_payload,
    parse_message_payload,
)
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

_STABLE_CLIENT_EMPTY_SENDER = ""
_STABLE_CLIENT_EMPTY_SENDER_ID = 0


def _hex_payload(*parts: str) -> bytes:
    return b"".join(bytes.fromhex(part) for part in parts)


def test_message_payload_round_trips_channel_message() -> None:
    payload = message_payload(
        sender="sender",
        content="hello",
        target="#osu",
        sender_id=42,
    )

    result = parse_message_payload(payload, packet_name="SEND_MESSAGE")

    assert result.sender == "sender"
    assert result.content == "hello"
    assert result.target == "#osu"
    assert result.sender_id == 42


def test_message_payload_round_trips_private_message() -> None:
    payload = message_payload(
        sender="sender",
        content="secret",
        target="target",
        sender_id=42,
    )

    result = parse_message_payload(payload, packet_name="SEND_PRIVATE_MESSAGE")

    assert result.sender == "sender"
    assert result.content == "secret"
    assert result.target == "target"
    assert result.sender_id == 42


def test_message_payload_accepts_stable_client_empty_sender_encoding() -> None:
    payload = _hex_payload(
        "0b00",  # sender: stable client empty string compatibility encoding
        "0b0e6177646177646177646177646177",  # content: awdawdawdawdaw
        "0b04236f7375",  # target: #osu
        "00000000",  # sender_id
    )

    result = parse_message_payload(payload, packet_name="SEND_MESSAGE")

    assert len(payload) == 28
    assert result.sender == ""
    assert result.content == "awdawdawdawdaw"
    assert result.target == "#osu"
    assert result.sender_id == 0


def test_private_message_payload_accepts_stable_client_empty_sender_encoding() -> None:
    payload = _hex_payload(
        "0b00",  # sender: stable client empty string compatibility encoding
        "0b0474657374",  # content: test
        "0b09546172676574557372",  # target: TargetUsr
        "00000000",  # sender_id
    )

    result = parse_message_payload(payload, packet_name="SEND_PRIVATE_MESSAGE")

    assert len(payload) == 23
    assert result.sender == ""
    assert result.content == "test"
    assert result.target == "TargetUsr"
    assert result.sender_id == 0


def test_message_payload_builds_stable_client_empty_sender_encoding() -> None:
    payload = message_payload(
        sender=_STABLE_CLIENT_EMPTY_SENDER,
        content="test",
        target="TargetUsr",
        sender_id=_STABLE_CLIENT_EMPTY_SENDER_ID,
    )

    assert payload == bytes.fromhex("0b000b04746573740b0954617267657455737200000000")


def test_message_payload_rejects_too_small_payload() -> None:
    with pytest.raises(PacketReadError, match="SEND_MESSAGE payload must be at least"):
        _ = parse_message_payload(b"\x00\x00", packet_name="SEND_MESSAGE")


def test_message_payload_rejects_trailing_bytes() -> None:
    payload = message_payload(sender="s", content="c", target="#osu", sender_id=1)

    with pytest.raises(PacketReadError, match="trailing or non-canonical bytes"):
        _ = parse_message_payload(payload + b"\x00", packet_name="SEND_MESSAGE")


def test_channel_name_payload_round_trips_join_and_leave_channel() -> None:
    payload = channel_name_payload("#osu")

    assert parse_channel_name_payload(payload, packet_name="JOIN_CHANNEL") == "#osu"
    assert parse_channel_name_payload(payload, packet_name="LEAVE_CHANNEL") == "#osu"


def test_channel_name_payload_rejects_invalid_string_payload() -> None:
    with pytest.raises(PacketReadError):
        _ = parse_channel_name_payload(b"\x0c", packet_name="JOIN_CHANNEL")


def test_channel_name_payload_rejects_trailing_bytes() -> None:
    payload = channel_name_payload("#osu")

    with pytest.raises(PacketReadError, match="trailing or non-canonical bytes"):
        _ = parse_channel_name_payload(payload + b"\x00", packet_name="LEAVE_CHANNEL")

"""stable C2S friend packet payload の wire contract を検証する."""

import pytest

from osu_server.transports.stable.bancho.protocol.c2s import (
    friend_only_dms_payload,
    friend_user_id_payload,
    parse_friend_only_dms_payload,
    parse_friend_user_id_payload,
)
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError


def test_friend_user_id_payload_round_trips_signed_int() -> None:
    """ADD_FRIEND の signed int32 user ID payload が round trip することを検証する."""
    payload = friend_user_id_payload(42)

    result = parse_friend_user_id_payload(payload, packet_name="ADD_FRIEND")

    assert payload == b"\x2a\x00\x00\x00"
    assert result == 42


def test_friend_user_id_payload_supports_signed_negative_values() -> None:
    """REMOVE_FRIEND payload が signed int32 の負値を保持することを検証する."""
    payload = friend_user_id_payload(-1)

    result = parse_friend_user_id_payload(payload, packet_name="REMOVE_FRIEND")

    assert payload == b"\xff\xff\xff\xff"
    assert result == -1


def test_friend_user_id_payload_rejects_wrong_size() -> None:
    """4 byte 以外の friend user ID payload を packet name ごとに拒否することを検証する."""
    with pytest.raises(PacketReadError, match="ADD_FRIEND payload must be 4 bytes"):
        _ = parse_friend_user_id_payload(b"\x01\x02", packet_name="ADD_FRIEND")

    with pytest.raises(PacketReadError, match="REMOVE_FRIEND payload must be 4 bytes"):
        _ = parse_friend_user_id_payload(
            b"\x01\x02\x03\x04\x05",
            packet_name="REMOVE_FRIEND",
        )


def test_friend_only_dms_payload_round_trips_enabled_flag() -> None:
    """friend-only DM flag の True と False が 1 byte wire値へ round trip することを検証する."""
    assert friend_only_dms_payload(True) == b"\x01"
    assert friend_only_dms_payload(False) == b"\x00"
    assert parse_friend_only_dms_payload(b"\x01") is True
    assert parse_friend_only_dms_payload(b"\x00") is False


def test_friend_only_dms_payload_rejects_wrong_size() -> None:
    """1 byte 以外の friend-only DM flag payload を拒否することを検証する."""
    with pytest.raises(PacketReadError, match="payload must be 1 bytes"):
        _ = parse_friend_only_dms_payload(b"")

    with pytest.raises(PacketReadError, match="payload must be 1 bytes"):
        _ = parse_friend_only_dms_payload(b"\x00\x01")


def test_friend_only_dms_payload_rejects_non_boolean_wire_value() -> None:
    """0 と 1 以外の friend-only DM flag wire値を拒否することを検証する."""
    with pytest.raises(PacketReadError, match="enabled must be 0 or 1"):
        _ = parse_friend_only_dms_payload(b"\x02")

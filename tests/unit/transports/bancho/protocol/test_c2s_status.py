"""stable C2S STATUS_CHANGE payload の wire contract を検証する."""

import pytest

from osu_server.transports.stable.bancho.protocol.c2s import (
    parse_status_change_payload,
    status_change_payload,
)
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.types import StatusUpdate


def test_status_change_payload_round_trips_status_update() -> None:
    """Canonical StatusUpdate payload が全 status field を round trip することを検証する."""
    payload = status_change_payload(
        StatusUpdate(
            status=2,
            status_text="playing",
            beatmap_md5="3b0aecd99eba50ffc7bff8da117d0e06",
            mods=0,
            play_mode=0,
            beatmap_id=1234,
        )
    )

    result = parse_status_change_payload(payload)

    assert result.status == 2
    assert result.status_text == "playing"
    assert result.beatmap_md5 == "3b0aecd99eba50ffc7bff8da117d0e06"
    assert result.mods == 0
    assert result.play_mode == 0
    assert result.beatmap_id == 1234


def test_status_change_payload_accepts_stable_client_present_empty_strings() -> None:
    """Stable client の present-empty string 表現を STATUS_CHANGE として許容することを検証する."""
    payload = bytes.fromhex("000b000b0000000000016bb92000")

    result = parse_status_change_payload(payload)

    assert result.status == 0
    assert result.status_text == ""
    assert result.beatmap_md5 == ""
    assert result.mods == 0
    assert result.play_mode == 1
    assert result.beatmap_id == 2_144_619


def test_status_change_payload_rejects_malformed_payload() -> None:
    """不完全な STATUS_CHANGE payload を PacketReadError で拒否することを検証する."""
    with pytest.raises(PacketReadError):
        _ = parse_status_change_payload(b"\x02\x0b")


def test_status_change_payload_rejects_trailing_bytes() -> None:
    """Canonical STATUS_CHANGE payload に続く余分な byte を拒否することを検証する."""
    payload = status_change_payload(
        StatusUpdate(
            status=2,
            status_text="playing",
            beatmap_md5="",
            mods=0,
            play_mode=0,
            beatmap_id=1234,
        )
    )

    with pytest.raises(PacketReadError, match="trailing or non-canonical bytes"):
        _ = parse_status_change_payload(payload + b"\x00")

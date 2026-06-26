"""UserStats golden bytes fixture tests."""

from __future__ import annotations

import struct as pystruct
from dataclasses import dataclass
from io import BytesIO
from typing import cast

from osu_server.transports.stable.bancho.protocol.c2s import (
    parse_status_change_payload,
    status_change_payload,
)
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats
from osu_server.transports.stable.bancho.protocol.types import StatusUpdate


@dataclass(frozen=True, slots=True)
class _DecodedStatusUpdate:
    status: int
    status_text: str
    beatmap_md5: str
    mods: int
    play_mode: int
    beatmap_id: int


@dataclass(frozen=True, slots=True)
class _DecodedStats:
    user_id: int
    status_update: _DecodedStatusUpdate
    ranked_score: int
    accuracy: float
    play_count: int
    total_score: int
    rank: int
    pp: int


def _read_exact(stream: BytesIO, size: int) -> bytes:
    data = stream.read(size)
    assert len(data) == size
    return data


def _read_i32(stream: BytesIO) -> int:
    return cast("int", pystruct.unpack("<i", _read_exact(stream, 4))[0])


def _read_i64(stream: BytesIO) -> int:
    return cast("int", pystruct.unpack("<q", _read_exact(stream, 8))[0])


def _read_u16(stream: BytesIO) -> int:
    return cast("int", pystruct.unpack("<H", _read_exact(stream, 2))[0])


def _read_u8(stream: BytesIO) -> int:
    return _read_exact(stream, 1)[0]


def _read_f32(stream: BytesIO) -> float:
    return cast("float", pystruct.unpack("<f", _read_exact(stream, 4))[0])


def _read_string(stream: BytesIO) -> str:
    marker = _read_u8(stream)
    if marker == 0:
        return ""
    assert marker == 0x0B

    length = _read_u8(stream)
    return _read_exact(stream, length).decode("utf-8")


def _read_status_update(stream: BytesIO) -> _DecodedStatusUpdate:
    return _DecodedStatusUpdate(
        status=_read_u8(stream),
        status_text=_read_string(stream),
        beatmap_md5=_read_string(stream),
        mods=_read_i32(stream),
        play_mode=_read_u8(stream),
        beatmap_id=_read_i32(stream),
    )


def _decode_stats(payload: bytes) -> _DecodedStats:
    stream = BytesIO(payload)
    result = _DecodedStats(
        user_id=_read_i32(stream),
        status_update=_read_status_update(stream),
        ranked_score=_read_i64(stream),
        accuracy=_read_f32(stream),
        play_count=_read_i32(stream),
        total_score=_read_i64(stream),
        rank=_read_i32(stream),
        pp=_read_u16(stream),
    )
    assert stream.read() == b""
    return result


def _payload(packet: bytes) -> bytes:
    return packet[7:]


def _packet_id(packet: bytes) -> int:
    return cast("int", pystruct.unpack_from("<H", packet, 0)[0])


def test_user_stats_packet_id() -> None:
    packet = user_stats(
        user_id=1,
        status=0,
        status_text="",
        beatmap_md5="",
        mods=0,
        play_mode=0,
        beatmap_id=0,
        ranked_score=0,
        accuracy=0.0,
        play_count=0,
        total_score=0,
        rank=0,
        pp=0,
    )

    assert _packet_id(packet) == ServerPacketID.USER_STATS


def test_user_stats_payload_matches_golden_bytes_and_decodes() -> None:
    expected = (
        b"\x2a\x00\x00\x00"
        b"\x02"
        b"\x0b\x07Playing"
        b"\x0b\x20"
        b"3b0aecd99eba50ffc7bff8da117d0e06"
        b"\x18\x00\x00\x00"
        b"\x00"
        b"\xd2\x04\x00\x00"
        b"\x15\xcd\x5b\x07\x00\x00\x00\x00"
        b"\xf6\x28\x7c\x3f"
        b"\x41\x01\x00\x00"
        b"\xea\x16\xb0\x4c\x02\x00\x00\x00"
        b"\x4d\x00\x00\x00"
        b"\x31\xd4"
    )

    payload = _payload(
        user_stats(
            user_id=42,
            status=2,
            status_text="Playing",
            beatmap_md5="3b0aecd99eba50ffc7bff8da117d0e06",
            mods=24,
            play_mode=0,
            beatmap_id=1234,
            ranked_score=123456789,
            accuracy=0.985,
            play_count=321,
            total_score=9876543210,
            rank=77,
            pp=54321,
        )
    )

    assert payload == expected
    decoded = _decode_stats(expected)
    assert decoded.user_id == 42
    assert decoded.status_update == _DecodedStatusUpdate(
        status=2,
        status_text="Playing",
        beatmap_md5="3b0aecd99eba50ffc7bff8da117d0e06",
        mods=24,
        play_mode=0,
        beatmap_id=1234,
    )
    assert decoded.ranked_score == 123456789
    assert abs(decoded.accuracy - 0.985) < 0.000001
    assert decoded.play_count == 321
    assert decoded.total_score == 9876543210
    assert decoded.rank == 77
    assert decoded.pp == 54321


def test_user_stats_clamps_pp_to_uint16_max() -> None:
    payload = _payload(
        user_stats(
            user_id=42,
            status=0,
            status_text="",
            beatmap_md5="",
            mods=0,
            play_mode=0,
            beatmap_id=0,
            ranked_score=0,
            accuracy=0.0,
            play_count=0,
            total_score=0,
            rank=0,
            pp=70000,
        )
    )

    assert payload[-2:] == b"\xff\xff"
    assert _decode_stats(payload).pp == 65535


def test_banchobot_user_stats_payload_matches_golden_bytes_and_decodes() -> None:
    expected = (
        b"\x01\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
        b"\x00\x00"
    )

    payload = _payload(
        user_stats(
            user_id=1,
            status=0,
            status_text="",
            beatmap_md5="",
            mods=0,
            play_mode=0,
            beatmap_id=0,
            ranked_score=0,
            accuracy=0.0,
            play_count=0,
            total_score=0,
            rank=0,
            pp=0,
        )
    )

    assert payload == expected
    decoded = _decode_stats(expected)
    assert decoded == _DecodedStats(
        user_id=1,
        status_update=_DecodedStatusUpdate(
            status=0,
            status_text="",
            beatmap_md5="",
            mods=0,
            play_mode=0,
            beatmap_id=0,
        ),
        ranked_score=0,
        accuracy=0.0,
        play_count=0,
        total_score=0,
        rank=0,
        pp=0,
    )


def test_status_change_payload_matches_golden_bytes_and_decodes_empty_strings() -> None:
    expected = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    status_update = StatusUpdate(
        status=0,
        status_text="",
        beatmap_md5="",
        mods=0,
        play_mode=0,
        beatmap_id=0,
    )

    assert status_change_payload(status_update) == expected

    decoded = parse_status_change_payload(expected)
    assert decoded.status == 0
    assert decoded.status_text == ""
    assert decoded.beatmap_md5 == ""
    assert decoded.mods == 0
    assert decoded.play_mode == 0
    assert decoded.beatmap_id == 0

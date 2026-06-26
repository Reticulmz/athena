"""UserPresence golden bytes fixture tests."""

from __future__ import annotations

import struct as pystruct
from dataclasses import dataclass
from io import BytesIO
from typing import cast

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    user_presence,
    user_presence_bundle,
)


@dataclass(frozen=True, slots=True)
class _DecodedPresence:
    user_id: int
    username: str
    timezone: int
    country_id: int
    permissions_mode: int
    longitude: float
    latitude: float
    rank: int


def _read_exact(stream: BytesIO, size: int) -> bytes:
    data = stream.read(size)
    assert len(data) == size
    return data


def _read_i32(stream: BytesIO) -> int:
    return cast("int", pystruct.unpack("<i", _read_exact(stream, 4))[0])


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


def _decode_presence(payload: bytes) -> _DecodedPresence:
    stream = BytesIO(payload)
    result = _DecodedPresence(
        user_id=_read_i32(stream),
        username=_read_string(stream),
        timezone=_read_u8(stream),
        country_id=_read_u8(stream),
        permissions_mode=_read_u8(stream),
        longitude=_read_f32(stream),
        latitude=_read_f32(stream),
        rank=_read_i32(stream),
    )
    assert stream.read() == b""
    return result


def _decode_int_list(payload: bytes) -> list[int]:
    stream = BytesIO(payload)
    count = _read_u16(stream)
    result = [_read_i32(stream) for _ in range(count)]
    assert stream.read() == b""
    return result


def _payload(packet: bytes) -> bytes:
    return packet[7:]


def _packet_id(packet: bytes) -> int:
    return cast("int", pystruct.unpack_from("<H", packet, 0)[0])


def test_user_presence_packet_id() -> None:
    packet = user_presence(
        user_id=1,
        username="test",
        timezone=24,
        country_id=0,
        permissions=1,
        mode=0,
        longitude=0.0,
        latitude=0.0,
        rank=1,
    )

    assert _packet_id(packet) == ServerPacketID.USER_PRESENCE


def test_user_presence_payload_matches_golden_bytes_and_decodes() -> None:
    expected = (
        b"\x2a\x00\x00\x00\x0b\x04user\x18\x01\x70\x00\xc0\x0b\x43\x00\x00\x0e\x42\x64\x00\x00\x00"
    )

    payload = _payload(
        user_presence(
            user_id=42,
            username="user",
            timezone=24,
            country_id=1,
            permissions=16,
            mode=3,
            longitude=139.75,
            latitude=35.5,
            rank=100,
        )
    )

    assert payload == expected
    decoded = _decode_presence(expected)
    assert decoded == _DecodedPresence(
        user_id=42,
        username="user",
        timezone=24,
        country_id=1,
        permissions_mode=112,
        longitude=139.75,
        latitude=35.5,
        rank=100,
    )


def test_banchobot_user_presence_payload_matches_golden_bytes_and_decodes() -> None:
    expected = (
        b"\x01\x00\x00\x00"
        b"\x0b\x09BanchoBot"
        b"\x18\x00\x10"
        b"\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
    )

    payload = _payload(
        user_presence(
            user_id=1,
            username="BanchoBot",
            timezone=24,
            country_id=0,
            permissions=16,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
    )

    assert payload == expected
    decoded = _decode_presence(expected)
    assert decoded == _DecodedPresence(
        user_id=1,
        username="BanchoBot",
        timezone=24,
        country_id=0,
        permissions_mode=16,
        longitude=0.0,
        latitude=0.0,
        rank=0,
    )


def test_user_presence_bundle_payload_matches_golden_bytes_and_decodes() -> None:
    expected = b"\x03\x00\x01\x00\x00\x00\x2a\x00\x00\x00\x64\x00\x00\x00"

    payload = _payload(user_presence_bundle([1, 42, 100]))

    assert payload == expected
    assert _decode_int_list(expected) == [1, 42, 100]


def test_user_presence_bundle_packet_id() -> None:
    packet = user_presence_bundle([5, 10])

    assert _packet_id(packet) == ServerPacketID.USER_PRESENCE_BUNDLE

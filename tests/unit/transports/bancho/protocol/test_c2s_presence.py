from __future__ import annotations

import pytest

from osu_server.transports.stable.bancho.protocol.c2s import (
    parse_presence_request_all_payload,
    parse_presence_request_payload,
    presence_request_payload,
)
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError


def test_presence_request_payload_round_trips_user_ids() -> None:
    payload = presence_request_payload([3, 1, 42])

    assert parse_presence_request_payload(payload) == (3, 1, 42)


def test_presence_request_rejects_more_than_256_user_ids() -> None:
    payload = presence_request_payload(list(range(257)))

    with pytest.raises(PacketReadError, match="at most 256 ids"):
        _ = parse_presence_request_payload(payload)


def test_presence_request_rejects_trailing_bytes() -> None:
    payload = presence_request_payload([3]) + b"\x00"

    with pytest.raises(PacketReadError, match="trailing or non-canonical"):
        _ = parse_presence_request_payload(payload)


def test_presence_request_all_accepts_empty_payload() -> None:
    parse_presence_request_all_payload(b"")


def test_presence_request_all_accepts_bancho_py_reserved_int32_payload() -> None:
    parse_presence_request_all_payload(b"\x00\x00\x00\x00")


def test_presence_request_all_rejects_unknown_payload_size() -> None:
    with pytest.raises(PacketReadError, match="empty or a reserved int32"):
        parse_presence_request_all_payload(b"\x00")

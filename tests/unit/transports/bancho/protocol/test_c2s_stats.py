"""Tests for stable C2S stats request packet payloads."""

from __future__ import annotations

import pytest

from osu_server.transports.stable.bancho.protocol.c2s import (
    parse_stats_request_payload,
    stats_request_payload,
)
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError


def test_stats_request_payload_matches_canonical_int_list_fixture() -> None:
    expected = b"\x03\x00\x2a\x00\x00\x00\x01\x00\x00\x00\x00\x01\x00\x00"

    assert stats_request_payload([42, 1, 256]) == expected
    assert parse_stats_request_payload(expected) == (42, 1, 256)


def test_stats_request_preserves_user_id_order() -> None:
    payload = stats_request_payload([7, 3, 7, 1])

    assert parse_stats_request_payload(payload) == (7, 3, 7, 1)


def test_stats_request_rejects_more_than_256_user_ids() -> None:
    payload = stats_request_payload(list(range(257)))

    with pytest.raises(PacketReadError, match="at most 256 ids"):
        _ = parse_stats_request_payload(payload)


def test_stats_request_rejects_trailing_bytes() -> None:
    payload = stats_request_payload([42]) + b"\x00"

    with pytest.raises(PacketReadError, match="trailing or non-canonical"):
        _ = parse_stats_request_payload(payload)


def test_stats_request_rejects_malformed_payload() -> None:
    with pytest.raises(PacketReadError):
        _ = parse_stats_request_payload(b"\x01")

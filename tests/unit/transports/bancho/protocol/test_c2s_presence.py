"""stable C2S presence request payload の受理条件を検証する."""

from __future__ import annotations

import pytest

import osu_server.transports.stable.bancho.protocol.c2s.presence as c2s_presence
from osu_server.transports.stable.bancho.protocol.c2s import (
    parse_presence_request_all_payload,
    parse_presence_request_payload,
    presence_request_payload,
)
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError


def test_presence_request_payload_round_trips_user_ids() -> None:
    """PRESENCE_REQUEST payload が user ID の wire順を復元することを検証する."""
    payload = presence_request_payload([3, 1, 42])

    assert parse_presence_request_payload(payload) == (3, 1, 42)


def test_presence_request_rejects_more_than_256_user_ids() -> None:
    """256件を超える PRESENCE_REQUEST user ID を拒否することを検証する."""
    payload = presence_request_payload(list(range(257)))

    with pytest.raises(PacketReadError, match="at most 256 ids"):
        _ = parse_presence_request_payload(payload)


def test_presence_request_rejects_trailing_bytes() -> None:
    """Canonical PRESENCE_REQUEST payload に続く余分な byte を拒否することを検証する."""
    payload = presence_request_payload([3]) + b"\x00"

    with pytest.raises(PacketReadError, match="trailing or non-canonical"):
        _ = parse_presence_request_payload(payload)


def test_presence_request_all_accepts_empty_payload() -> None:
    """空の PRESENCE_REQUEST_ALL payload を許容することを検証する."""
    parse_presence_request_all_payload(b"")


def test_presence_request_all_accepts_bancho_py_reserved_int32_payload() -> None:
    """bancho.py 互換の reserved int32 PRESENCE_REQUEST_ALL payload を許容することを検証する."""
    parse_presence_request_all_payload(b"\x00\x00\x00\x00")


def test_presence_request_all_wraps_reserved_payload_unpack_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reserved int32 decode の失敗を PacketReadError に包むことを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): unpack を失敗する fake に差し替える fixture.
    """

    def raise_runtime_error(_struct_type: object, _payload: bytes) -> object:
        """Reserved payload decoder の runtime failure を再現する.

        Args:
            _struct_type (object): unpack に渡される struct type.
            _payload (bytes): unpack に渡される reserved payload.

        Raises:
            RuntimeError: fixed test failure を示すため常に送出する.
        """
        raise RuntimeError("boom")

    monkeypatch.setattr(c2s_presence, "unpack", raise_runtime_error)

    with pytest.raises(PacketReadError, match="boom"):
        parse_presence_request_all_payload(b"\x00\x00\x00\x00")


def test_presence_request_all_rejects_unknown_payload_size() -> None:
    """空でも reserved int32 でもない PRESENCE_REQUEST_ALL payload を拒否することを検証する."""
    with pytest.raises(PacketReadError, match="empty or a reserved int32"):
        parse_presence_request_all_payload(b"\x00")

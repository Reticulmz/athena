"""Tests for S2C login packet builders.

Validates:
- Req 6.1: LoginReply (int32: userId or error code)
- Req 6.2: ProtocolVersion (int32)
- Req 6.3: LoginPermissions (int32: permission bitmask)
- Req 6.4: Notification (BanchoString)
- Req 6.7: FriendsList (IntList)
- Req 6.8: ChannelAvailable / ChannelAvailableAutojoin (Channel payload)
- Req 6.9: ChannelInfoComplete (empty payload)
- Req 6.10: SilenceInfo (int32: remaining seconds)
- Req 6.12: All S2C packets use correct ServerPacketID
"""

import struct as pystruct
from typing import cast

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    channel_available,
    channel_available_autojoin,
    channel_info_complete,
    friends_list,
    login_permissions,
    login_reply,
    notification,
    protocol_version,
    silence_info,
)


def _extract_packet_id(data: bytes) -> int:
    """Extract the ServerPacketID from the first 2 bytes of a packet."""
    return cast("int", pystruct.unpack_from("<H", data, 0)[0])


def _extract_payload(data: bytes) -> bytes:
    """Extract the payload (after 7-byte header) from a packet."""
    return data[7:]


# ── Task 4.1: Scalar payload packets ────────────────────────────────


class TestLoginReply:
    """Req 6.1: LoginReply — int32 (positive=userId, negative=error)."""

    def test_packet_id(self) -> None:
        assert _extract_packet_id(login_reply(100)) == ServerPacketID.LOGIN_REPLY

    def test_positive_user_id(self) -> None:
        payload = _extract_payload(login_reply(100))
        assert pystruct.unpack("<i", payload)[0] == 100

    def test_negative_error_code(self) -> None:
        payload = _extract_payload(login_reply(-1))
        assert pystruct.unpack("<i", payload)[0] == -1

    def test_known_bytes(self) -> None:
        result = login_reply(100)
        expected = b"\x05\x00\x00\x04\x00\x00\x00\x64\x00\x00\x00"
        assert result == expected


class TestProtocolVersion:
    """Req 6.2: ProtocolVersion — int32."""

    def test_packet_id(self) -> None:
        assert _extract_packet_id(protocol_version(19)) == ServerPacketID.PROTOCOL_VERSION

    def test_version_value(self) -> None:
        payload = _extract_payload(protocol_version(19))
        assert pystruct.unpack("<i", payload)[0] == 19


class TestLoginPermissions:
    """Req 6.3: LoginPermissions — int32 (bitmask)."""

    def test_packet_id(self) -> None:
        assert _extract_packet_id(login_permissions(4)) == ServerPacketID.LOGIN_PERMISSIONS

    def test_bitmask_value(self) -> None:
        payload = _extract_payload(login_permissions(4))
        assert pystruct.unpack("<i", payload)[0] == 4


class TestNotification:
    """Req 6.4: Notification — BanchoString."""

    def test_packet_id(self) -> None:
        assert _extract_packet_id(notification("hello")) == ServerPacketID.ANNOUNCE

    def test_empty_notification(self) -> None:
        payload = _extract_payload(notification(""))
        assert payload == b"\x00"

    def test_non_empty_notification(self) -> None:
        payload = _extract_payload(notification("hi"))
        # 0x0b 0x02 "hi"
        assert payload == b"\x0b\x02hi"


class TestChannelInfoComplete:
    """Req 6.9: ChannelInfoComplete — empty payload."""

    def test_packet_id(self) -> None:
        assert _extract_packet_id(channel_info_complete()) == ServerPacketID.CHANNEL_INFO_COMPLETE

    def test_empty_payload(self) -> None:
        payload = _extract_payload(channel_info_complete())
        assert payload == b""

    def test_total_length(self) -> None:
        assert len(channel_info_complete()) == 7


class TestSilenceInfo:
    """Req 6.10: SilenceInfo — int32 (remaining seconds)."""

    def test_packet_id(self) -> None:
        assert _extract_packet_id(silence_info(300)) == ServerPacketID.SILENCE_INFO

    def test_silence_value(self) -> None:
        payload = _extract_payload(silence_info(300))
        assert pystruct.unpack("<i", payload)[0] == 300

    def test_zero_silence(self) -> None:
        payload = _extract_payload(silence_info(0))
        assert pystruct.unpack("<i", payload)[0] == 0


class TestFriendsList:
    """Req 6.7: FriendsList — IntList."""

    def test_packet_id(self) -> None:
        assert _extract_packet_id(friends_list([1, 2, 3])) == ServerPacketID.FRIENDS_LIST

    def test_friend_ids(self) -> None:
        payload = _extract_payload(friends_list([10, 20]))
        count: int = cast("int", pystruct.unpack_from("<H", payload, 0)[0])
        assert count == 2
        vals = pystruct.unpack_from("<2i", payload, 2)
        assert vals == (10, 20)

    def test_empty_friends(self) -> None:
        payload = _extract_payload(friends_list([]))
        count: int = cast("int", pystruct.unpack_from("<H", payload, 0)[0])
        assert count == 0


class TestChannelAvailable:
    """Req 6.8: ChannelAvailable — Channel payload."""

    def test_packet_id(self) -> None:
        result = channel_available(name="#osu", topic="General", user_count=100)
        assert _extract_packet_id(result) == ServerPacketID.CHANNEL_AVAILABLE

    def test_autojoin_packet_id(self) -> None:
        result = channel_available_autojoin(name="#osu", topic="General", user_count=100)
        assert _extract_packet_id(result) == ServerPacketID.CHANNEL_AVAILABLE_AUTOJOIN

    def test_different_packet_ids(self) -> None:
        r1 = channel_available(name="#a", topic="", user_count=0)
        r2 = channel_available_autojoin(name="#a", topic="", user_count=0)
        assert _extract_packet_id(r1) != _extract_packet_id(r2)

    def test_same_payload(self) -> None:
        """Both share the same Channel payload format."""
        r1 = channel_available(name="#osu", topic="chat", user_count=50)
        r2 = channel_available_autojoin(name="#osu", topic="chat", user_count=50)
        assert _extract_payload(r1) == _extract_payload(r2)

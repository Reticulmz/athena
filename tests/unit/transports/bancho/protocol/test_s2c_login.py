# ruff: noqa: PLR2004
# pyright: reportUnknownMemberType=false
"""Tests for S2C login packet builders.

Validates:
- Req 6.1: LoginReply (int32: userId or error code)
- Req 6.2: ProtocolVersion (int32)
- Req 6.3: LoginPermissions (int32: permission bitmask)
- Req 6.4: Notification (BanchoString)
- Req 6.5: UserPresence (complex struct)
- Req 6.6: UserStats (complex struct)
- Req 6.7: FriendsList (IntList)
- Req 6.8: ChannelAvailable / ChannelAvailableAutojoin (Channel payload)
- Req 6.9: ChannelInfoComplete (empty payload)
- Req 6.10: SilenceInfo (int32: remaining seconds)
- Req 6.11: UserPresenceBundle (IntList: user IDs)
- Req 6.12: All S2C packets use correct ServerPacketID
"""

import struct as pystruct
from typing import cast

from osu_server.transports.bancho.protocol.enums import ServerPacketID
from osu_server.transports.bancho.protocol.s2c.login import (
    channel_available,
    channel_available_autojoin,
    channel_info_complete,
    friends_list,
    login_permissions,
    login_reply,
    notification,
    protocol_version,
    silence_info,
    user_presence,
    user_presence_bundle,
    user_stats,
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


class TestUserPresenceBundle:
    """Req 6.11: UserPresenceBundle — IntList (user IDs)."""

    def test_packet_id(self) -> None:
        assert (
            _extract_packet_id(user_presence_bundle([5, 10]))
            == ServerPacketID.USER_PRESENCE_BUNDLE
        )

    def test_user_ids(self) -> None:
        payload = _extract_payload(user_presence_bundle([100, 200, 300]))
        count: int = cast("int", pystruct.unpack_from("<H", payload, 0)[0])
        assert count == 3


# ── Task 4.2: Complex payload packets ───────────────────────────────


class TestUserPresence:
    """Req 6.5: UserPresence — complex struct."""

    def test_packet_id(self) -> None:
        result = user_presence(
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
        assert _extract_packet_id(result) == ServerPacketID.USER_PRESENCE

    def test_payload_starts_with_user_id(self) -> None:
        result = user_presence(
            user_id=42,
            username="user",
            timezone=24,
            country_id=0,
            permissions=1,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=100,
        )
        payload = _extract_payload(result)
        uid: int = cast("int", pystruct.unpack_from("<i", payload, 0)[0])
        assert uid == 42

    def test_permissions_mode_packed(self) -> None:
        """Permissions | (Mode << 5) packed into one byte."""
        result = user_presence(
            user_id=1,
            username="u",
            timezone=24,
            country_id=0,
            permissions=4,
            mode=2,
            longitude=0.0,
            latitude=0.0,
            rank=1,
        )
        payload = _extract_payload(result)
        # After user_id(4) + username(BanchoString) + timezone(1) + country_id(1)
        # username "u" = 0x0b 0x01 0x75 = 3 bytes
        # packed_byte at offset 4+3+1+1 = 9
        packed = payload[9]
        assert packed == (4 | (2 << 5))


class TestUserStats:
    """Req 6.6: UserStats — complex struct."""

    def test_packet_id(self) -> None:
        result = user_stats(
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
        assert _extract_packet_id(result) == ServerPacketID.USER_STATS

    def test_payload_starts_with_user_id(self) -> None:
        result = user_stats(
            user_id=99,
            status=2,
            status_text="Playing",
            beatmap_md5="abc",
            mods=0,
            play_mode=0,
            beatmap_id=1,
            ranked_score=1000,
            accuracy=98.5,
            play_count=50,
            total_score=5000,
            rank=100,
            pp=300,
        )
        payload = _extract_payload(result)
        uid: int = cast("int", pystruct.unpack_from("<i", payload, 0)[0])
        assert uid == 99


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

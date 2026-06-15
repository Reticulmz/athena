"""Tests for bancho wire types.

Validates:
- Req 3.1: BanchoString type (presence byte 0x00 = empty, 0x0b = ULEB128 length + UTF-8)
- Req 3.2: Message type (sender, content, target BanchoStrings + sender_id int32)
- Req 3.3: IntList type (uint16 count + int32[] dynamic array)
- Req 3.4: Channel type (name, topic BanchoStrings + user_count int16)
- Req 3.5: StatusUpdate type (status, status_text, beatmap_md5, mods, play_mode, beatmap_id)
- Req 3.6: Bidirectional conversion (parse + build) for all wire types
"""

import struct as pystruct
from typing import Annotated, cast

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import uint8
from caterpillar.model import pack, struct, unpack

from osu_server.transports.stable.bancho.protocol.types import (
    BanchoString,
    BanchoStringT,
    Channel,
    IntList,
    Message,
    StatusUpdate,
)


class TestBanchoStringPackEmpty:
    """Req 3.1: empty string packs to presence byte 0x00."""

    def test_pack_empty_string(self) -> None:
        data = pack("", LittleEndian + BanchoString)
        assert data == b"\x00"

    def test_pack_empty_string_is_one_byte(self) -> None:
        data = pack("", LittleEndian + BanchoString)
        assert len(data) == 1


class TestBanchoStringPackASCII:
    """Req 3.1: non-empty string packs to 0x0b + ULEB128 length + UTF-8 data."""

    def test_pack_short_ascii(self) -> None:
        """'hi' → 0x0b 0x02 0x68 0x69."""
        data = pack("hi", LittleEndian + BanchoString)
        assert data == b"\x0b\x02\x68\x69"

    def test_pack_presence_byte_is_0x0b(self) -> None:
        data = pack("a", LittleEndian + BanchoString)
        assert data[0:1] == b"\x0b"

    def test_pack_length_is_uleb128(self) -> None:
        """String of length 128 → ULEB128 length = 0x80 0x01."""
        text = "a" * 128
        data = pack(text, LittleEndian + BanchoString)
        # presence byte + ULEB128(128) = 0x80 0x01 + 128 bytes
        assert data[1:3] == b"\x80\x01"
        assert len(data) == 1 + 2 + 128

    def test_pack_data_is_utf8(self) -> None:
        data = pack("ABC", LittleEndian + BanchoString)
        # Skip presence byte and length byte
        assert data[2:] == b"ABC"


class TestBanchoStringPackMultibyte:
    """Req 3.1: multi-byte UTF-8 strings."""

    def test_pack_japanese(self) -> None:
        text = "こんにちは"
        data = pack(text, LittleEndian + BanchoString)
        utf8_bytes = text.encode("utf-8")
        # presence=0x0b, length=15 (ULEB128=0x0f), then UTF-8 data
        assert data[0:1] == b"\x0b"
        assert data[1:2] == bytes([len(utf8_bytes)])
        assert data[2:] == utf8_bytes

    def test_pack_emoji(self) -> None:
        text = "🎵"
        data = pack(text, LittleEndian + BanchoString)
        utf8_bytes = text.encode("utf-8")
        assert data[0:1] == b"\x0b"
        assert data[2:] == utf8_bytes


class TestBanchoStringUnpackEmpty:
    """Req 3.1: presence byte 0x00 unpacks to empty string."""

    def test_unpack_empty_string(self) -> None:
        result = cast("str", unpack(BanchoString, b"\x00"))
        assert result == ""

    def test_unpack_empty_string_type(self) -> None:
        result = cast("str", unpack(BanchoString, b"\x00"))
        assert isinstance(result, str)


class TestBanchoStringUnpackASCII:
    """Req 3.1: 0x0b + ULEB128 length + UTF-8 data unpacks to string."""

    def test_unpack_short_ascii(self) -> None:
        """0x0b 0x02 0x68 0x69 → 'hi'."""
        result = cast("str", unpack(BanchoString, b"\x0b\x02\x68\x69"))
        assert result == "hi"

    def test_unpack_single_char(self) -> None:
        result = cast("str", unpack(BanchoString, b"\x0b\x01\x41"))
        assert result == "A"


class TestBanchoStringUnpackMultibyte:
    """Req 3.1: multi-byte UTF-8 unpacking."""

    def test_unpack_japanese(self) -> None:
        text = "こんにちは"
        utf8_bytes = text.encode("utf-8")
        wire = b"\x0b" + bytes([len(utf8_bytes)]) + utf8_bytes
        result = cast("str", unpack(BanchoString, wire))
        assert result == text

    def test_unpack_emoji(self) -> None:
        text = "🎵"
        utf8_bytes = text.encode("utf-8")
        wire = b"\x0b" + bytes([len(utf8_bytes)]) + utf8_bytes
        result = cast("str", unpack(BanchoString, wire))
        assert result == text


class TestBanchoStringRoundTrip:
    """Req 3.6: unpack(pack(s)) == s for all string types."""

    def test_roundtrip_empty(self) -> None:
        original = ""
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_ascii(self) -> None:
        original = "hello world"
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_multibyte_utf8(self) -> None:
        original = "こんにちは世界"
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_mixed_content(self) -> None:
        original = "user123 — テスト 🎮"
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_long_string(self) -> None:
        """String longer than 127 bytes exercises multi-byte ULEB128."""
        original = "x" * 300
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_uleb128_boundary(self) -> None:
        """Exactly 127 bytes — single-byte ULEB128 boundary."""
        original = "a" * 127
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_uleb128_two_byte(self) -> None:
        """Exactly 128 bytes — first two-byte ULEB128 value."""
        original = "b" * 128
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original


class TestBanchoStringInStruct:
    """BanchoString nestable as field in Caterpillar struct."""

    def test_struct_with_bancho_string_field(self) -> None:
        @struct(order=LittleEndian)
        class TestPacket:
            value: Annotated[int, uint8]
            name: BanchoStringT

        original = TestPacket(value=42, name="hello")
        data = pack(original)
        restored = unpack(TestPacket, data)
        assert restored.value == 42
        assert restored.name == "hello"

    def test_struct_with_empty_bancho_string(self) -> None:
        @struct(order=LittleEndian)
        class TestPacket:
            value: Annotated[int, uint8]
            name: BanchoStringT

        original = TestPacket(value=0, name="")
        data = pack(original)
        restored = unpack(TestPacket, data)
        assert restored.value == 0
        assert restored.name == ""

    def test_struct_with_multiple_bancho_strings(self) -> None:
        @struct(order=LittleEndian)
        class MultiString:
            first: BanchoStringT
            second: BanchoStringT

        original = MultiString(first="hello", second="world")
        data = pack(original)
        restored = unpack(MultiString, data)
        assert restored.first == "hello"
        assert restored.second == "world"


# ── Message (Req 3.2, 3.6) ──────────────────────────────────────────


class TestMessagePack:
    """Req 3.2: Message has sender, content, target (BanchoString) + sender_id (int32)."""

    def test_pack_known_message(self) -> None:
        msg = Message(sender="user", content="hello", target="#osu", sender_id=1000)
        data = pack(msg)
        # sender_id should be last 4 bytes, little-endian
        assert data[-4:] == pystruct.pack("<i", 1000)

    def test_pack_has_three_bancho_strings(self) -> None:
        msg = Message(sender="a", content="b", target="c", sender_id=0)
        data = pack(msg)
        # Each non-empty 1-char string: 0x0b 0x01 <char> = 3 bytes
        # 3 strings * 3 bytes + 4 bytes sender_id = 13
        assert len(data) == 13

    def test_pack_empty_strings(self) -> None:
        msg = Message(sender="", content="", target="", sender_id=-1)
        data = pack(msg)
        # 3 empty strings (0x00 each) + 4 bytes sender_id = 7
        assert len(data) == 7


class TestMessageUnpack:
    """Req 3.2: Message unpacks from binary."""

    def test_unpack_known_message(self) -> None:
        msg = Message(sender="user", content="hello", target="#osu", sender_id=1000)
        data = pack(msg)
        restored = unpack(Message, data)
        assert restored.sender == "user"
        assert restored.content == "hello"
        assert restored.target == "#osu"
        assert restored.sender_id == 1000


class TestMessageRoundTrip:
    """Req 3.6: unpack(pack(msg)) == msg."""

    def test_roundtrip_typical(self) -> None:
        original = Message(sender="peppy", content="Welcome!", target="#announce", sender_id=2)
        data = pack(original)
        restored = unpack(Message, data)
        assert restored.sender == original.sender
        assert restored.content == original.content
        assert restored.target == original.target
        assert restored.sender_id == original.sender_id

    def test_roundtrip_negative_sender_id(self) -> None:
        original = Message(sender="sys", content="error", target="user1", sender_id=-1)
        data = pack(original)
        restored = unpack(Message, data)
        assert restored.sender_id == -1

    def test_roundtrip_multibyte(self) -> None:
        original = Message(sender="ユーザー", content="こんにちは", target="#日本語", sender_id=42)
        data = pack(original)
        restored = unpack(Message, data)
        assert restored.sender == original.sender
        assert restored.content == original.content
        assert restored.target == original.target


# ── IntList (Req 3.3, 3.6) ──────────────────────────────────────────


class TestIntListPack:
    """Req 3.3: IntList has uint16 count + int32[] dynamic array."""

    def test_pack_known_values(self) -> None:
        il = IntList(count=3, values=[1, 2, 3])
        data = pack(il)
        # count (2 bytes) + 3 * int32 (12 bytes) = 14 bytes
        assert len(data) == 14
        assert data[:2] == pystruct.pack("<H", 3)

    def test_pack_empty_list(self) -> None:
        il = IntList(count=0, values=[])
        data = pack(il)
        # count only, 2 bytes
        assert len(data) == 2
        assert data == pystruct.pack("<H", 0)

    def test_pack_values_are_little_endian_int32(self) -> None:
        il = IntList(count=1, values=[0x01020304])
        data = pack(il)
        assert data[2:6] == pystruct.pack("<i", 0x01020304)


class TestIntListUnpack:
    """Req 3.3: IntList unpacks from binary."""

    def test_unpack_known_values(self) -> None:
        il = IntList(count=2, values=[100, 200])
        data = pack(il)
        restored = unpack(IntList, data)
        assert restored.count == 2
        assert list(restored.values) == [100, 200]


class TestIntListRoundTrip:
    """Req 3.6: unpack(pack(il)) == il."""

    def test_roundtrip_typical(self) -> None:
        original = IntList(count=4, values=[10, 20, 30, 40])
        data = pack(original)
        restored = unpack(IntList, data)
        assert restored.count == 4
        assert list(restored.values) == [10, 20, 30, 40]

    def test_roundtrip_negative_values(self) -> None:
        original = IntList(count=2, values=[-1, -100])
        data = pack(original)
        restored = unpack(IntList, data)
        assert list(restored.values) == [-1, -100]

    def test_roundtrip_empty(self) -> None:
        original = IntList(count=0, values=[])
        data = pack(original)
        restored = unpack(IntList, data)
        assert restored.count == 0
        assert list(restored.values) == []


# ── Channel (Req 3.4, 3.6) ──────────────────────────────────────────


class TestChannelPack:
    """Req 3.4: Channel has name, topic (BanchoString) + user_count (int16)."""

    def test_pack_known_channel(self) -> None:
        ch = Channel(name="#osu", topic="General chat", user_count=150)
        data = pack(ch)
        # user_count is last 2 bytes LE
        assert data[-2:] == pystruct.pack("<h", 150)

    def test_pack_empty_topic(self) -> None:
        ch = Channel(name="#test", topic="", user_count=0)
        data = pack(ch)
        assert data is not None
        assert len(data) > 0


class TestChannelRoundTrip:
    """Req 3.6: unpack(pack(ch)) == ch."""

    def test_roundtrip_typical(self) -> None:
        original = Channel(name="#osu", topic="Main channel", user_count=500)
        data = pack(original)
        restored = unpack(Channel, data)
        assert restored.name == "#osu"
        assert restored.topic == "Main channel"
        assert restored.user_count == 500

    def test_roundtrip_multibyte(self) -> None:
        original = Channel(name="#日本語", topic="日本語チャンネル", user_count=10)
        data = pack(original)
        restored = unpack(Channel, data)
        assert restored.name == original.name
        assert restored.topic == original.topic
        assert restored.user_count == 10


# ── StatusUpdate (Req 3.5, 3.6) ─────────────────────────────────────


class TestStatusUpdatePack:
    """Req 3.5: StatusUpdate has status, status_text, beatmap_md5, mods, play_mode, beatmap_id."""

    def test_pack_known_status(self) -> None:
        su = StatusUpdate(
            status=2,
            status_text="Playing",
            beatmap_md5="abc123",
            mods=64,
            play_mode=0,
            beatmap_id=12345,
        )
        data = pack(su)
        assert data is not None
        # first byte is status
        assert data[0] == 2

    def test_pack_idle_status(self) -> None:
        su = StatusUpdate(
            status=0,
            status_text="",
            beatmap_md5="",
            mods=0,
            play_mode=0,
            beatmap_id=0,
        )
        data = pack(su)
        # status(1) + 2 empty strings(1+1) + mods(4) + play_mode(1) + beatmap_id(4) = 12
        assert len(data) == 12


class TestStatusUpdateRoundTrip:
    """Req 3.6: unpack(pack(su)) == su."""

    def test_roundtrip_typical(self) -> None:
        original = StatusUpdate(
            status=2,
            status_text="Listening",
            beatmap_md5="d41d8cd98f00b204e9800998ecf8427e",
            mods=64,
            play_mode=0,
            beatmap_id=99999,
        )
        data = pack(original)
        restored = unpack(StatusUpdate, data)
        assert restored.status == 2
        assert restored.status_text == "Listening"
        assert restored.beatmap_md5 == original.beatmap_md5
        assert restored.mods == 64
        assert restored.play_mode == 0
        assert restored.beatmap_id == 99999

    def test_roundtrip_all_zeros(self) -> None:
        original = StatusUpdate(
            status=0, status_text="", beatmap_md5="", mods=0, play_mode=0, beatmap_id=0
        )
        data = pack(original)
        restored = unpack(StatusUpdate, data)
        assert restored.status == 0
        assert restored.status_text == ""
        assert restored.mods == 0

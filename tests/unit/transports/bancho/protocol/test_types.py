# ruff: noqa: PLR2004
# pyright: reportUnknownMemberType=false
"""Tests for BanchoString custom FieldStruct.

Validates:
- Req 3.1: BanchoString type (presence byte 0x00 = empty, 0x0b = ULEB128 length + UTF-8)
- Req 3.6: Bidirectional conversion (parse + build) for all wire types
"""

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import uint8
from caterpillar.model import pack, struct, unpack

from osu_server.transports.bancho.protocol.types import BanchoString


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
        result = unpack(BanchoString, b"\x00")
        assert result == ""

    def test_unpack_empty_string_type(self) -> None:
        result = unpack(BanchoString, b"\x00")
        assert isinstance(result, str)


class TestBanchoStringUnpackASCII:
    """Req 3.1: 0x0b + ULEB128 length + UTF-8 data unpacks to string."""

    def test_unpack_short_ascii(self) -> None:
        """0x0b 0x02 0x68 0x69 → 'hi'."""
        result = unpack(BanchoString, b"\x0b\x02\x68\x69")
        assert result == "hi"

    def test_unpack_single_char(self) -> None:
        result = unpack(BanchoString, b"\x0b\x01\x41")
        assert result == "A"


class TestBanchoStringUnpackMultibyte:
    """Req 3.1: multi-byte UTF-8 unpacking."""

    def test_unpack_japanese(self) -> None:
        text = "こんにちは"
        utf8_bytes = text.encode("utf-8")
        wire = b"\x0b" + bytes([len(utf8_bytes)]) + utf8_bytes
        result = unpack(BanchoString, wire)
        assert result == text

    def test_unpack_emoji(self) -> None:
        text = "🎵"
        utf8_bytes = text.encode("utf-8")
        wire = b"\x0b" + bytes([len(utf8_bytes)]) + utf8_bytes
        result = unpack(BanchoString, wire)
        assert result == text


class TestBanchoStringRoundTrip:
    """Req 3.6: unpack(pack(s)) == s for all string types."""

    def test_roundtrip_empty(self) -> None:
        original = ""
        data = pack(original, LittleEndian + BanchoString)
        restored = unpack(BanchoString, data)
        assert restored == original

    def test_roundtrip_ascii(self) -> None:
        original = "hello world"
        data = pack(original, LittleEndian + BanchoString)
        restored = unpack(BanchoString, data)
        assert restored == original

    def test_roundtrip_multibyte_utf8(self) -> None:
        original = "こんにちは世界"
        data = pack(original, LittleEndian + BanchoString)
        restored = unpack(BanchoString, data)
        assert restored == original

    def test_roundtrip_mixed_content(self) -> None:
        original = "user123 — テスト 🎮"
        data = pack(original, LittleEndian + BanchoString)
        restored = unpack(BanchoString, data)
        assert restored == original

    def test_roundtrip_long_string(self) -> None:
        """String longer than 127 bytes exercises multi-byte ULEB128."""
        original = "x" * 300
        data = pack(original, LittleEndian + BanchoString)
        restored = unpack(BanchoString, data)
        assert restored == original

    def test_roundtrip_uleb128_boundary(self) -> None:
        """Exactly 127 bytes — single-byte ULEB128 boundary."""
        original = "a" * 127
        data = pack(original, LittleEndian + BanchoString)
        restored = unpack(BanchoString, data)
        assert restored == original

    def test_roundtrip_uleb128_two_byte(self) -> None:
        """Exactly 128 bytes — first two-byte ULEB128 value."""
        original = "b" * 128
        data = pack(original, LittleEndian + BanchoString)
        restored = unpack(BanchoString, data)
        assert restored == original


class TestBanchoStringInStruct:
    """BanchoString nestable as field in Caterpillar struct."""

    def test_struct_with_bancho_string_field(self) -> None:
        @struct(order=LittleEndian)
        class TestPacket:
            value: uint8  # pyright: ignore[reportInvalidTypeForm]
            name: BanchoString  # pyright: ignore[reportInvalidTypeForm]

        original = TestPacket(value=42, name="hello")
        data = pack(original)
        restored = unpack(TestPacket, data)
        assert restored.value == 42
        assert restored.name == "hello"

    def test_struct_with_empty_bancho_string(self) -> None:
        @struct(order=LittleEndian)
        class TestPacket:
            value: uint8  # pyright: ignore[reportInvalidTypeForm]
            name: BanchoString  # pyright: ignore[reportInvalidTypeForm]

        original = TestPacket(value=0, name="")
        data = pack(original)
        restored = unpack(TestPacket, data)
        assert restored.value == 0
        assert restored.name == ""

    def test_struct_with_multiple_bancho_strings(self) -> None:
        @struct(order=LittleEndian)
        class MultiString:
            first: BanchoString  # pyright: ignore[reportInvalidTypeForm]
            second: BanchoString  # pyright: ignore[reportInvalidTypeForm]

        original = MultiString(first="hello", second="world")
        data = pack(original)
        restored = unpack(MultiString, data)
        assert restored.first == "hello"
        assert restored.second == "world"

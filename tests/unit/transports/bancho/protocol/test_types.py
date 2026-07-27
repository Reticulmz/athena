"""Bancho wire typeのpack/unpack contractを検証する.

BanchoStringのpresence byteとULEB128, Message, IntList, Channel, StatusUpdateの
little-endian wire format, および各型のround tripを対象にする.
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
    """空文字列のBanchoString pack wire contractを検証する."""

    def test_pack_empty_string(self) -> None:
        """空文字列をpackしたとき0x00だけが出力されることを検証する.

        Returns:
            None: empty presence byteだけのwire valueを確認して完了する.
        """
        data = pack("", LittleEndian + BanchoString)
        assert data == b"\x00"

    def test_pack_empty_string_is_one_byte(self) -> None:
        """空文字列のwire representationが1 byteで完結することを検証する.

        Returns:
            None: empty presence byteの出力長を確認して完了する.
        """
        data = pack("", LittleEndian + BanchoString)
        assert len(data) == 1


class TestBanchoStringPackASCII:
    """ASCII文字列のBanchoString pack wire contractを検証する."""

    def test_pack_short_ascii(self) -> None:
        """短いASCII文字列が既知のBanchoString bytesへpackされることを検証する.

        Returns:
            None: hiのpresence byte, ULEB128 length, UTF-8 dataを確認して完了する.
        """
        data = pack("hi", LittleEndian + BanchoString)
        assert data == b"\x0b\x02\x68\x69"

    def test_pack_presence_byte_is_0x0b(self) -> None:
        """非空文字列の先頭byteが0x0bであることを検証する.

        Returns:
            None: string presence byteのwire valueを確認して完了する.
        """
        data = pack("a", LittleEndian + BanchoString)
        assert data[0:1] == b"\x0b"

    def test_pack_length_is_uleb128(self) -> None:
        """128 byte文字列の長さが2 byte ULEB128になることを検証する.

        Returns:
            None: 0x80 0x01のlength bytesとpayload長を確認して完了する.
        """
        text = "a" * 128
        data = pack(text, LittleEndian + BanchoString)
        # presence byte + ULEB128(128) = 0x80 0x01 + 128 bytes
        assert data[1:3] == b"\x80\x01"
        assert len(data) == 1 + 2 + 128

    def test_pack_data_is_utf8(self) -> None:
        """ASCII payloadがUTF-8 dataとしてheaderの後ろへ書かれることを検証する.

        Returns:
            None: presence byteとlength byteを除いたpayload bytesを確認して完了する.
        """
        data = pack("ABC", LittleEndian + BanchoString)
        # Skip presence byte and length byte
        assert data[2:] == b"ABC"


class TestBanchoStringPackMultibyte:
    """multi-byte UTF-8文字列のBanchoString pack contractを検証する."""

    def test_pack_japanese(self) -> None:
        """日本語文字列のUTF-8 byte長とpayloadがwire formatへ反映されることを検証する.

        Returns:
            None: 0x0b, UTF-8 byte長, UTF-8 payloadの順序を確認して完了する.
        """
        text = "こんにちは"
        data = pack(text, LittleEndian + BanchoString)
        utf8_bytes = text.encode("utf-8")
        # presence=0x0b, length=15 (ULEB128=0x0f), then UTF-8 data
        assert data[0:1] == b"\x0b"
        assert data[1:2] == bytes([len(utf8_bytes)])
        assert data[2:] == utf8_bytes

    def test_pack_emoji(self) -> None:
        """emojiのUTF-8 payloadが非空BanchoStringとしてpackされることを検証する.

        Returns:
            None: 0x0bのpresence byteとemojiのUTF-8 dataを確認して完了する.
        """
        text = "🎵"
        data = pack(text, LittleEndian + BanchoString)
        utf8_bytes = text.encode("utf-8")
        assert data[0:1] == b"\x0b"
        assert data[2:] == utf8_bytes


class TestBanchoStringUnpackEmpty:
    """空BanchoStringのunpack wire contractを検証する."""

    def test_unpack_empty_string(self) -> None:
        """0x00 presence byteが空文字列へunpackされることを検証する.

        Returns:
            None: empty wire valueの復元結果を確認して完了する.
        """
        result = cast("str", unpack(BanchoString, b"\x00"))
        assert result == ""

    def test_unpack_empty_string_type(self) -> None:
        """空BanchoStringのunpack結果がstrであることを検証する.

        Returns:
            None: runtime typeがstrであることを確認して完了する.
        """
        result = cast("str", unpack(BanchoString, b"\x00"))
        assert isinstance(result, str)


class TestBanchoStringUnpackASCII:
    """ASCII BanchoStringのunpack wire contractを検証する."""

    def test_unpack_short_ascii(self) -> None:
        """既知のASCII wire bytesがhiへunpackされることを検証する.

        Returns:
            None: presence byte, ULEB128 length, UTF-8 dataからの復元結果を確認して完了する.
        """
        result = cast("str", unpack(BanchoString, b"\x0b\x02\x68\x69"))
        assert result == "hi"

    def test_unpack_single_char(self) -> None:
        """1文字のASCII BanchoStringが正しい文字列へunpackされることを検証する.

        Returns:
            None: Aのwire representationからの復元結果を確認して完了する.
        """
        result = cast("str", unpack(BanchoString, b"\x0b\x01\x41"))
        assert result == "A"


class TestBanchoStringUnpackMultibyte:
    """multi-byte UTF-8 BanchoStringのunpack contractを検証する."""

    def test_unpack_japanese(self) -> None:
        """日本語UTF-8 payloadが元の文字列へunpackされることを検証する.

        Returns:
            None: byte長を含むwire valueからの日本語文字列を確認して完了する.
        """
        text = "こんにちは"
        utf8_bytes = text.encode("utf-8")
        wire = b"\x0b" + bytes([len(utf8_bytes)]) + utf8_bytes
        result = cast("str", unpack(BanchoString, wire))
        assert result == text

    def test_unpack_emoji(self) -> None:
        """emojiのUTF-8 payloadが元の文字列へunpackされることを検証する.

        Returns:
            None: byte長を含むwire valueからのemojiを確認して完了する.
        """
        text = "🎵"
        utf8_bytes = text.encode("utf-8")
        wire = b"\x0b" + bytes([len(utf8_bytes)]) + utf8_bytes
        result = cast("str", unpack(BanchoString, wire))
        assert result == text


class TestBanchoStringRoundTrip:
    """BanchoStringのpack/unpack round trip contractを検証する."""

    def test_roundtrip_empty(self) -> None:
        """空文字列がpack/unpack後も空文字列であることを検証する.

        Returns:
            None: empty inputのround trip結果を確認して完了する.
        """
        original = ""
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_ascii(self) -> None:
        """ASCII文字列がpack/unpack後も同じ値であることを検証する.

        Returns:
            None: ASCII inputのround trip結果を確認して完了する.
        """
        original = "hello world"
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_multibyte_utf8(self) -> None:
        """multi-byte UTF-8文字列がpack/unpack後も同じ値であることを検証する.

        Returns:
            None: 日本語inputのround trip結果を確認して完了する.
        """
        original = "こんにちは世界"
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_mixed_content(self) -> None:
        """ASCII, 日本語, emojiを含む文字列のround tripを検証する.

        Returns:
            None: mixed UTF-8 inputの復元結果を確認して完了する.
        """
        original = "user123 — テスト 🎮"
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_long_string(self) -> None:
        """127 byteを超える文字列がmulti-byte ULEB128でround tripすることを検証する.

        Returns:
            None: 300 byte inputの復元結果を確認して完了する.
        """
        original = "x" * 300
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_uleb128_boundary(self) -> None:
        """127 byte境界の文字列がsingle-byte ULEB128でround tripすることを検証する.

        Returns:
            None: 境界値inputの復元結果を確認して完了する.
        """
        original = "a" * 127
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original

    def test_roundtrip_uleb128_two_byte(self) -> None:
        """128 byte文字列が最初のtwo-byte ULEB128値でround tripすることを検証する.

        Returns:
            None: 128 byte inputの復元結果を確認して完了する.
        """
        original = "b" * 128
        data = pack(original, LittleEndian + BanchoString)
        restored = cast("str", unpack(BanchoString, data))
        assert restored == original


class TestBanchoStringInStruct:
    """Caterpillar struct内のBanchoString field contractを検証する."""

    def test_struct_with_bancho_string_field(self) -> None:
        """uint8 fieldとBanchoString fieldを持つstructのround tripを検証する.

        Returns:
            None: valueとnameの両fieldが復元されることを確認して完了する.
        """

        @struct(order=LittleEndian)
        class TestPacket:
            """uint8 valueとBanchoString nameを持つ一時packet modelを定義する.

            Attributes:
                value (int): uint8として符号化するpacket value.
                name (str): BanchoStringとして符号化するpacket名.
            """

            value: Annotated[int, uint8]
            name: BanchoStringT

        original = TestPacket(value=42, name="hello")
        data = pack(original)
        restored = unpack(TestPacket, data)
        assert restored.value == 42
        assert restored.name == "hello"

    def test_struct_with_empty_bancho_string(self) -> None:
        """struct内の空BanchoString fieldがround tripすることを検証する.

        Returns:
            None: uint8 valueとempty nameが復元されることを確認して完了する.
        """

        @struct(order=LittleEndian)
        class TestPacket:
            """uint8 valueと空BanchoString nameを持つ一時packet modelを定義する.

            Attributes:
                value (int): uint8として符号化するpacket value.
                name (str): 空文字列を許容するBanchoString field.
            """

            value: Annotated[int, uint8]
            name: BanchoStringT

        original = TestPacket(value=0, name="")
        data = pack(original)
        restored = unpack(TestPacket, data)
        assert restored.value == 0
        assert restored.name == ""

    def test_struct_with_multiple_bancho_strings(self) -> None:
        """複数のBanchoString fieldを持つstructのround tripを検証する.

        Returns:
            None: firstとsecondの文字列が順序どおり復元されることを確認して完了する.
        """

        @struct(order=LittleEndian)
        class MultiString:
            """2つのBanchoString fieldを持つ一時packet modelを定義する.

            Attributes:
                first (str): 先に符号化するBanchoString field.
                second (str): firstの後に符号化するBanchoString field.
            """

            first: BanchoStringT
            second: BanchoStringT

        original = MultiString(first="hello", second="world")
        data = pack(original)
        restored = unpack(MultiString, data)
        assert restored.first == "hello"
        assert restored.second == "world"


# ── Message (Req 3.2, 3.6) ──────────────────────────────────────────


class TestMessagePack:
    """Messageのpack wire contractを検証する."""

    def test_pack_known_message(self) -> None:
        """既知のMessageでsender_idが末尾little-endian int32になることを検証する.

        Returns:
            None: sender_id 1000の末尾4 bytesを確認して完了する.
        """
        msg = Message(sender="user", content="hello", target="#osu", sender_id=1000)
        data = pack(msg)
        # sender_id should be last 4 bytes, little-endian
        assert data[-4:] == pystruct.pack("<i", 1000)

    def test_pack_has_three_bancho_strings(self) -> None:
        """3つの非空BanchoString fieldを持つMessageのwire長を検証する.

        Returns:
            None: 3つのstring fieldとint32 sender_idによる13 byte出力を確認して完了する.
        """
        msg = Message(sender="a", content="b", target="c", sender_id=0)
        data = pack(msg)
        # Each non-empty 1-char string: 0x0b 0x01 <char> = 3 bytes
        # 3 strings * 3 bytes + 4 bytes sender_id = 13
        assert len(data) == 13

    def test_pack_empty_strings(self) -> None:
        """空string fieldを持つMessageのwire長を検証する.

        Returns:
            None: 3つのempty presence byteとint32 sender_idによる7 byte出力を確認して完了する.
        """
        msg = Message(sender="", content="", target="", sender_id=-1)
        data = pack(msg)
        # 3 empty strings (0x00 each) + 4 bytes sender_id = 7
        assert len(data) == 7


class TestMessageUnpack:
    """Messageのunpack wire contractを検証する."""

    def test_unpack_known_message(self) -> None:
        """pack済みの既知Messageが各fieldへunpackされることを検証する.

        Returns:
            None: sender, content, target, sender_idの復元結果を確認して完了する.
        """
        msg = Message(sender="user", content="hello", target="#osu", sender_id=1000)
        data = pack(msg)
        restored = unpack(Message, data)
        assert restored.sender == "user"
        assert restored.content == "hello"
        assert restored.target == "#osu"
        assert restored.sender_id == 1000


class TestMessageRoundTrip:
    """Messageのpack/unpack round trip contractを検証する."""

    def test_roundtrip_typical(self) -> None:
        """通常のMessageがpack/unpack後も各fieldを保持することを検証する.

        Returns:
            None: sender, content, target, sender_idのround trip結果を確認して完了する.
        """
        original = Message(sender="peppy", content="Welcome!", target="#announce", sender_id=2)
        data = pack(original)
        restored = unpack(Message, data)
        assert restored.sender == original.sender
        assert restored.content == original.content
        assert restored.target == original.target
        assert restored.sender_id == original.sender_id

    def test_roundtrip_negative_sender_id(self) -> None:
        """負のsender_idがMessage round tripで保持されることを検証する.

        Returns:
            None: signed int32の-1が復元されることを確認して完了する.
        """
        original = Message(sender="sys", content="error", target="user1", sender_id=-1)
        data = pack(original)
        restored = unpack(Message, data)
        assert restored.sender_id == -1

    def test_roundtrip_multibyte(self) -> None:
        """multi-byte UTF-8 fieldを持つMessageのround tripを検証する.

        Returns:
            None: sender, content, targetの日本語文字列が復元されることを確認して完了する.
        """
        original = Message(sender="ユーザー", content="こんにちは", target="#日本語", sender_id=42)
        data = pack(original)
        restored = unpack(Message, data)
        assert restored.sender == original.sender
        assert restored.content == original.content
        assert restored.target == original.target


# ── IntList (Req 3.3, 3.6) ──────────────────────────────────────────


class TestIntListPack:
    """IntListのpack wire contractを検証する."""

    def test_pack_known_values(self) -> None:
        """countと3つのint32 valueを持つIntListのwire layoutを検証する.

        Returns:
            None: uint16 countと3つのint32に対応する14 byte出力を確認して完了する.
        """
        il = IntList(count=3, values=[1, 2, 3])
        data = pack(il)
        # count (2 bytes) + 3 * int32 (12 bytes) = 14 bytes
        assert len(data) == 14
        assert data[:2] == pystruct.pack("<H", 3)

    def test_pack_empty_list(self) -> None:
        """空IntListがuint16 countだけへpackされることを検証する.

        Returns:
            None: count 0の2 byte little-endian representationを確認して完了する.
        """
        il = IntList(count=0, values=[])
        data = pack(il)
        # count only, 2 bytes
        assert len(data) == 2
        assert data == pystruct.pack("<H", 0)

    def test_pack_values_are_little_endian_int32(self) -> None:
        """IntList valueがlittle-endian signed int32としてpackされることを検証する.

        Returns:
            None: 0x01020304のwire bytesを確認して完了する.
        """
        il = IntList(count=1, values=[0x01020304])
        data = pack(il)
        assert data[2:6] == pystruct.pack("<i", 0x01020304)


class TestIntListUnpack:
    """IntListのunpack wire contractを検証する."""

    def test_unpack_known_values(self) -> None:
        """pack済みIntListがcountとvaluesへunpackされることを検証する.

        Returns:
            None: count 2と2つのvalueの復元結果を確認して完了する.
        """
        il = IntList(count=2, values=[100, 200])
        data = pack(il)
        restored = unpack(IntList, data)
        assert restored.count == 2
        assert list(restored.values) == [100, 200]


class TestIntListRoundTrip:
    """IntListのpack/unpack round trip contractを検証する."""

    def test_roundtrip_typical(self) -> None:
        """複数valueを持つIntListがround tripすることを検証する.

        Returns:
            None: count 4と4つのvalueが復元されることを確認して完了する.
        """
        original = IntList(count=4, values=[10, 20, 30, 40])
        data = pack(original)
        restored = unpack(IntList, data)
        assert restored.count == 4
        assert list(restored.values) == [10, 20, 30, 40]

    def test_roundtrip_negative_values(self) -> None:
        """負のint32 valueを持つIntListがround tripすることを検証する.

        Returns:
            None: -1と-100のsigned valueが復元されることを確認して完了する.
        """
        original = IntList(count=2, values=[-1, -100])
        data = pack(original)
        restored = unpack(IntList, data)
        assert list(restored.values) == [-1, -100]

    def test_roundtrip_empty(self) -> None:
        """空IntListがround trip後も空であることを検証する.

        Returns:
            None: count 0と空valuesが復元されることを確認して完了する.
        """
        original = IntList(count=0, values=[])
        data = pack(original)
        restored = unpack(IntList, data)
        assert restored.count == 0
        assert list(restored.values) == []


# ── Channel (Req 3.4, 3.6) ──────────────────────────────────────────


class TestChannelPack:
    """Channelのpack wire contractを検証する."""

    def test_pack_known_channel(self) -> None:
        """既知Channelのuser_countが末尾little-endian int16になることを検証する.

        Returns:
            None: user_count 150の末尾2 bytesを確認して完了する.
        """
        ch = Channel(name="#osu", topic="General chat", user_count=150)
        data = pack(ch)
        # user_count is last 2 bytes LE
        assert data[-2:] == pystruct.pack("<h", 150)

    def test_pack_empty_topic(self) -> None:
        """空topicを持つChannelが有効なwire bytesへpackされることを検証する.

        Returns:
            None: empty topicでも非空のpacket representationが得られることを確認して完了する.
        """
        ch = Channel(name="#test", topic="", user_count=0)
        data = pack(ch)
        assert data is not None
        assert len(data) > 0


class TestChannelRoundTrip:
    """Channelのpack/unpack round trip contractを検証する."""

    def test_roundtrip_typical(self) -> None:
        """通常のChannelがpack/unpack後も各fieldを保持することを検証する.

        Returns:
            None: name, topic, user_countのround trip結果を確認して完了する.
        """
        original = Channel(name="#osu", topic="Main channel", user_count=500)
        data = pack(original)
        restored = unpack(Channel, data)
        assert restored.name == "#osu"
        assert restored.topic == "Main channel"
        assert restored.user_count == 500

    def test_roundtrip_multibyte(self) -> None:
        """日本語nameとtopicを持つChannelのround tripを検証する.

        Returns:
            None: multi-byte UTF-8 fieldとuser_countが復元されることを確認して完了する.
        """
        original = Channel(name="#日本語", topic="日本語チャンネル", user_count=10)
        data = pack(original)
        restored = unpack(Channel, data)
        assert restored.name == original.name
        assert restored.topic == original.topic
        assert restored.user_count == 10


# ── StatusUpdate (Req 3.5, 3.6) ─────────────────────────────────────


class TestStatusUpdatePack:
    """StatusUpdateのpack wire contractを検証する."""

    def test_pack_known_status(self) -> None:
        """既知StatusUpdateのstatusが先頭uint8へpackされることを検証する.

        Returns:
            None: 非空wire valueの先頭byteがstatus 2であることを確認して完了する.
        """
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
        """Idle StatusUpdateの固定fieldと空string fieldによるwire長を検証する.

        Returns:
            None: 2つのempty presence byteを含む12 byte出力を確認して完了する.
        """
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
    """StatusUpdateのpack/unpack round trip contractを検証する."""

    def test_roundtrip_typical(self) -> None:
        """通常のStatusUpdateがpack/unpack後も各fieldを保持することを検証する.

        Returns:
            None: status, text, MD5, mods, mode, beatmap IDの復元結果を確認して完了する.
        """
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
        """zero値だけのStatusUpdateがpack/unpack後も保持されることを検証する.

        Returns:
            None: status, string field, modsのzero値が復元されることを確認して完了する.
        """
        original = StatusUpdate(
            status=0, status_text="", beatmap_md5="", mods=0, play_mode=0, beatmap_id=0
        )
        data = pack(original)
        restored = unpack(StatusUpdate, data)
        assert restored.status == 0
        assert restored.status_text == ""
        assert restored.mods == 0

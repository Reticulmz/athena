"""PacketHeader struct と HEADER_SIZE の stable Bancho wire contract を検証する.

header field, little-endian pack と unpack, 境界値の round trip を確認する.
"""

from caterpillar.model import pack, unpack

from osu_server.transports.stable.bancho.protocol.header import HEADER_SIZE, PacketHeader


class TestHeaderSize:
    """HEADER_SIZE constant の固定 wire size を検証する."""

    def test_header_size_is_seven(self) -> None:
        """Bancho packet header が常に 7 byte であることを検証する."""
        assert HEADER_SIZE == 7


class TestPacketHeaderFields:
    """PacketHeader の packet ID, compression, content size field を検証する."""

    def test_has_packet_id_field(self) -> None:
        """PacketHeader instance が packet_id field を公開することを検証する."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        assert hasattr(header, "packet_id")

    def test_has_compression_field(self) -> None:
        """PacketHeader instance が compression field を公開することを検証する."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        assert hasattr(header, "compression")

    def test_has_content_size_field(self) -> None:
        """PacketHeader instance が content_size field を公開することを検証する."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        assert hasattr(header, "content_size")

    def test_field_values_preserved(self) -> None:
        """PacketHeader constructor が各 field value を保持することを検証する."""
        header = PacketHeader(packet_id=42, compression=True, content_size=1024)
        assert header.packet_id == 42
        assert header.compression is True
        assert header.content_size == 1024


class TestPacketHeaderPack:
    """PacketHeader の 7 byte little-endian pack 結果を検証する."""

    def test_pack_produces_seven_bytes(self) -> None:
        """PacketHeader pack が HEADER_SIZE と同じ byte数を返すことを検証する."""
        header = PacketHeader(packet_id=5, compression=False, content_size=4)
        data = pack(header)
        assert len(data) == HEADER_SIZE

    def test_pack_known_login_reply_header(self) -> None:
        """LoginReply header が既知の 7 byte little-endian fixture に一致することを検証する."""
        header = PacketHeader(packet_id=5, compression=False, content_size=4)
        data = pack(header)
        assert data == b"\x05\x00\x00\x04\x00\x00\x00"

    def test_pack_zero_values(self) -> None:
        """全 field が 0 または False の header が 7 zero byte に pack されることを検証する."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        data = pack(header)
        assert data == b"\x00\x00\x00\x00\x00\x00\x00"

    def test_pack_max_packet_id(self) -> None:
        """uint16 packet ID の最大値が little-endian で pack されることを検証する."""
        header = PacketHeader(packet_id=0xFFFF, compression=False, content_size=0)
        data = pack(header)
        # Little-endian uint16: 0xFFFF → FF FF
        assert data[:2] == b"\xff\xff"

    def test_pack_max_content_size(self) -> None:
        """uint32 content size の最大値が little-endian で pack されることを検証する."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0xFFFFFFFF)
        data = pack(header)
        # Little-endian uint32: 0xFFFFFFFF → FF FF FF FF (last 4 bytes)
        assert data[3:] == b"\xff\xff\xff\xff"

    def test_pack_compression_true(self) -> None:
        """True compression flag が byte index 2 に 1 として pack されることを検証する."""
        header = PacketHeader(packet_id=0, compression=True, content_size=0)
        data = pack(header)
        assert data[2:3] == b"\x01"

    def test_pack_compression_false(self) -> None:
        """False compression flag が byte index 2 に 0 として pack されることを検証する."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        data = pack(header)
        assert data[2:3] == b"\x00"

    def test_pack_little_endian_packet_id(self) -> None:
        """Packet ID 0x0100 が little-endian で 00 01 に pack されることを検証する."""
        header = PacketHeader(packet_id=0x0100, compression=False, content_size=0)
        data = pack(header)
        assert data[:2] == b"\x00\x01"

    def test_pack_little_endian_content_size(self) -> None:
        """Content size 0x04030201 が little-endian で 01 02 03 04 に pack されることを検証する."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0x04030201)
        data = pack(header)
        assert data[3:] == b"\x01\x02\x03\x04"


class TestPacketHeaderUnpack:
    """7 byte little-endian stream からの PacketHeader unpack を検証する."""

    def test_unpack_known_login_reply_header(self) -> None:
        """既知の LoginReply header fixture が全 field に unpack されることを検証する."""
        data = b"\x05\x00\x00\x04\x00\x00\x00"
        header = unpack(PacketHeader, data)
        assert header.packet_id == 5
        assert header.compression is False
        assert header.content_size == 4

    def test_unpack_zero_values(self) -> None:
        """7 zero byte が zero value の PacketHeader に unpack されることを検証する."""
        data = b"\x00\x00\x00\x00\x00\x00\x00"
        header = unpack(PacketHeader, data)
        assert header.packet_id == 0
        assert header.compression is False
        assert header.content_size == 0

    def test_unpack_max_values(self) -> None:
        """最大 packet ID と content size が PacketHeader に unpack されることを検証する."""
        data = b"\xff\xff\x01\xff\xff\xff\xff"
        header = unpack(PacketHeader, data)
        assert header.packet_id == 0xFFFF
        assert header.compression is True
        assert header.content_size == 0xFFFFFFFF

    def test_unpack_little_endian_packet_id(self) -> None:
        """byte列 00 01 が little-endian packet ID 0x0100 に unpack されることを検証する."""
        data = b"\x00\x01\x00\x00\x00\x00\x00"
        header = unpack(PacketHeader, data)
        assert header.packet_id == 256

    def test_unpack_little_endian_content_size(self) -> None:
        """Offset 3 の content size bytes が little-endian で unpack されることを検証する."""
        data = b"\x00\x00\x00\x01\x02\x03\x04"
        header = unpack(PacketHeader, data)
        assert header.content_size == 0x04030201


class TestPacketHeaderRoundTrip:
    """PacketHeader の pack と unpack による round trip を検証する."""

    def test_roundtrip_typical_values(self) -> None:
        """通常の packet ID, compression, content size が round trip することを検証する."""
        original = PacketHeader(packet_id=83, compression=False, content_size=128)
        data = pack(original)
        restored = unpack(PacketHeader, data)
        assert restored.packet_id == original.packet_id
        assert restored.compression == original.compression
        assert restored.content_size == original.content_size

    def test_roundtrip_with_compression_true(self) -> None:
        """True compression flag を持つ header が round trip することを検証する."""
        original = PacketHeader(packet_id=7, compression=True, content_size=256)
        data = pack(original)
        restored = unpack(PacketHeader, data)
        assert restored.packet_id == original.packet_id
        assert restored.compression == original.compression
        assert restored.content_size == original.content_size

    def test_roundtrip_edge_case_max(self) -> None:
        """最大 field value を持つ header が round trip することを検証する."""
        original = PacketHeader(packet_id=0xFFFF, compression=True, content_size=0xFFFFFFFF)
        data = pack(original)
        restored = unpack(PacketHeader, data)
        assert restored.packet_id == original.packet_id
        assert restored.compression == original.compression
        assert restored.content_size == original.content_size

    def test_roundtrip_edge_case_zero(self) -> None:
        """Zero field value を持つ header が round trip することを検証する."""
        original = PacketHeader(packet_id=0, compression=False, content_size=0)
        data = pack(original)
        restored = unpack(PacketHeader, data)
        assert restored.packet_id == original.packet_id
        assert restored.compression == original.compression
        assert restored.content_size == original.content_size

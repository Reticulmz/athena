"""Tests for PacketHeader struct and HEADER_SIZE constant.

Validates:
- Req 1.1: PacketHeader has PacketID (uint16), Compression (bool), ContentSize (uint32)
- Req 1.2: All fields are little-endian
- Req 1.3: 7-byte stream → PacketHeader (unpack)
- Req 1.4: PacketHeader → 7 bytes (pack)
"""

from caterpillar.model import pack, unpack

from osu_server.transports.stable.bancho.protocol.header import HEADER_SIZE, PacketHeader


class TestHeaderSize:
    """HEADER_SIZE constant tests."""

    def test_header_size_is_seven(self) -> None:
        assert HEADER_SIZE == 7


class TestPacketHeaderFields:
    """Req 1.1: PacketHeader field composition."""

    def test_has_packet_id_field(self) -> None:
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        assert hasattr(header, "packet_id")

    def test_has_compression_field(self) -> None:
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        assert hasattr(header, "compression")

    def test_has_content_size_field(self) -> None:
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        assert hasattr(header, "content_size")

    def test_field_values_preserved(self) -> None:
        header = PacketHeader(packet_id=42, compression=True, content_size=1024)
        assert header.packet_id == 42
        assert header.compression is True
        assert header.content_size == 1024


class TestPacketHeaderPack:
    """Req 1.2, 1.4: PacketHeader → 7 bytes, little-endian."""

    def test_pack_produces_seven_bytes(self) -> None:
        header = PacketHeader(packet_id=5, compression=False, content_size=4)
        data = pack(header)
        assert len(data) == HEADER_SIZE

    def test_pack_known_login_reply_header(self) -> None:
        """LoginReply: ID=5, compression=False, content_size=4 → 05 00 00 04 00 00 00."""
        header = PacketHeader(packet_id=5, compression=False, content_size=4)
        data = pack(header)
        assert data == b"\x05\x00\x00\x04\x00\x00\x00"

    def test_pack_zero_values(self) -> None:
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        data = pack(header)
        assert data == b"\x00\x00\x00\x00\x00\x00\x00"

    def test_pack_max_packet_id(self) -> None:
        """PacketID is uint16 → max 65535 (0xFFFF)."""
        header = PacketHeader(packet_id=0xFFFF, compression=False, content_size=0)
        data = pack(header)
        # Little-endian uint16: 0xFFFF → FF FF
        assert data[:2] == b"\xff\xff"

    def test_pack_max_content_size(self) -> None:
        """ContentSize is uint32 → max 4294967295 (0xFFFFFFFF)."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0xFFFFFFFF)
        data = pack(header)
        # Little-endian uint32: 0xFFFFFFFF → FF FF FF FF (last 4 bytes)
        assert data[3:] == b"\xff\xff\xff\xff"

    def test_pack_compression_true(self) -> None:
        """Compression field occupies byte index 2."""
        header = PacketHeader(packet_id=0, compression=True, content_size=0)
        data = pack(header)
        assert data[2:3] == b"\x01"

    def test_pack_compression_false(self) -> None:
        header = PacketHeader(packet_id=0, compression=False, content_size=0)
        data = pack(header)
        assert data[2:3] == b"\x00"

    def test_pack_little_endian_packet_id(self) -> None:
        """PacketID=0x0100 should be stored as 00 01 in little-endian."""
        header = PacketHeader(packet_id=0x0100, compression=False, content_size=0)
        data = pack(header)
        assert data[:2] == b"\x00\x01"

    def test_pack_little_endian_content_size(self) -> None:
        """ContentSize=0x04030201 stored as 01 02 03 04 in little-endian."""
        header = PacketHeader(packet_id=0, compression=False, content_size=0x04030201)
        data = pack(header)
        assert data[3:] == b"\x01\x02\x03\x04"


class TestPacketHeaderUnpack:
    """Req 1.2, 1.3: 7 bytes → PacketHeader, little-endian."""

    def test_unpack_known_login_reply_header(self) -> None:
        """05 00 00 04 00 00 00 → ID=5, compression=False, content_size=4."""
        data = b"\x05\x00\x00\x04\x00\x00\x00"
        header = unpack(PacketHeader, data)
        assert header.packet_id == 5
        assert header.compression is False
        assert header.content_size == 4

    def test_unpack_zero_values(self) -> None:
        data = b"\x00\x00\x00\x00\x00\x00\x00"
        header = unpack(PacketHeader, data)
        assert header.packet_id == 0
        assert header.compression is False
        assert header.content_size == 0

    def test_unpack_max_values(self) -> None:
        data = b"\xff\xff\x01\xff\xff\xff\xff"
        header = unpack(PacketHeader, data)
        assert header.packet_id == 0xFFFF
        assert header.compression is True
        assert header.content_size == 0xFFFFFFFF

    def test_unpack_little_endian_packet_id(self) -> None:
        """Bytes 00 01 → PacketID=0x0100 (256) in little-endian."""
        data = b"\x00\x01\x00\x00\x00\x00\x00"
        header = unpack(PacketHeader, data)
        assert header.packet_id == 256

    def test_unpack_little_endian_content_size(self) -> None:
        """Bytes 01 02 03 04 at offset 3 → ContentSize=0x04030201 in little-endian."""
        data = b"\x00\x00\x00\x01\x02\x03\x04"
        header = unpack(PacketHeader, data)
        assert header.content_size == 0x04030201


class TestPacketHeaderRoundTrip:
    """Pack/unpack round-trip consistency."""

    def test_roundtrip_typical_values(self) -> None:
        original = PacketHeader(packet_id=83, compression=False, content_size=128)
        data = pack(original)
        restored = unpack(PacketHeader, data)
        assert restored.packet_id == original.packet_id
        assert restored.compression == original.compression
        assert restored.content_size == original.content_size

    def test_roundtrip_with_compression_true(self) -> None:
        original = PacketHeader(packet_id=7, compression=True, content_size=256)
        data = pack(original)
        restored = unpack(PacketHeader, data)
        assert restored.packet_id == original.packet_id
        assert restored.compression == original.compression
        assert restored.content_size == original.content_size

    def test_roundtrip_edge_case_max(self) -> None:
        original = PacketHeader(packet_id=0xFFFF, compression=True, content_size=0xFFFFFFFF)
        data = pack(original)
        restored = unpack(PacketHeader, data)
        assert restored.packet_id == original.packet_id
        assert restored.compression == original.compression
        assert restored.content_size == original.content_size

    def test_roundtrip_edge_case_zero(self) -> None:
        original = PacketHeader(packet_id=0, compression=False, content_size=0)
        data = pack(original)
        restored = unpack(PacketHeader, data)
        assert restored.packet_id == original.packet_id
        assert restored.compression == original.compression
        assert restored.content_size == original.content_size

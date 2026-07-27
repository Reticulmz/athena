"""S2C packet writerのwire bytesとlogging contractを検証する.

7 byte headerとpayloadの連結, compression flag, known packet bytes, quiet packetの
log levelを対象にする.
"""

import struct as pystruct
from typing import cast

import structlog.testing

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.writer import (
    QUIET_S2C_PACKETS,
    write_packet,
)

BANCHO_PACKET_HEADER_SIZE = 7


class TestWritePacketHeader:
    """write_packetが生成する7 byte S2C headerを検証する."""

    def test_header_size(self) -> None:
        """空payloadのpacketが7 byte headerだけを持つことを検証する.

        Returns:
            None: PING packetの出力長を確認して完了する.
        """
        result = write_packet(ServerPacketID.PING, b"")
        assert len(result) == BANCHO_PACKET_HEADER_SIZE

    def test_header_packet_id(self) -> None:
        """header先頭のuint16が指定したServerPacketIDになることを検証する.

        Returns:
            None: LOGIN_REPLYのlittle-endian packet IDを確認して完了する.
        """
        result = write_packet(ServerPacketID.LOGIN_REPLY, b"\x00" * 4)
        packet_id = cast("int", pystruct.unpack_from("<H", result, 0)[0])
        assert packet_id == ServerPacketID.LOGIN_REPLY

    def test_header_compression_always_false(self) -> None:
        """headerのcompression flagが常にFalseであることを検証する.

        Returns:
            None: PING packetのflag byteが0であることを確認して完了する.
        """
        result = write_packet(ServerPacketID.PING, b"")
        assert result[2] == 0  # compression = False

    def test_header_content_size(self) -> None:
        """headerのuint32 content sizeがpayload長と一致することを検証する.

        Returns:
            None: 4 byte payloadのcontent sizeを確認して完了する.
        """
        payload = b"\x01\x02\x03\x04"
        result = write_packet(ServerPacketID.PING, payload)
        content_size = cast("int", pystruct.unpack_from("<I", result, 3)[0])
        assert content_size == len(payload)


class TestWritePacketPayload:
    """write_packetがheader後にpayloadを連結することを検証する."""

    def test_empty_payload(self) -> None:
        """空payloadがheaderだけの既知bytesを生成することを検証する.

        Returns:
            None: PINGのpacket ID, false flag, size 0から成るheaderを確認して完了する.
        """
        result = write_packet(ServerPacketID.PING, b"")
        assert result == pystruct.pack("<HBI", ServerPacketID.PING, 0, 0)

    def test_payload_appended(self) -> None:
        """payloadが7 byte headerの直後に無変更で連結されることを検証する.

        Returns:
            None: payload sliceが入力bytesと一致することを確認して完了する.
        """
        payload = b"\xaa\xbb\xcc"
        result = write_packet(ServerPacketID.PING, payload)
        assert result[7:] == payload

    def test_total_length(self) -> None:
        """packet全体の長さがheader長とpayload長の和になることを検証する.

        Returns:
            None: 10 byte payloadを持つ17 byte packetを確認して完了する.
        """
        payload = b"\x01" * 10
        result = write_packet(ServerPacketID.PING, payload)
        assert len(result) == 7 + 10


class TestWritePacketKnownBytes:
    """既知のS2C packet byte sequenceを検証する."""

    def test_login_reply_packet(self) -> None:
        """User ID 100を持つLOGIN_REPLYの既知wire bytesを検証する.

        Returns:
            None: packet ID 5, false flag, payload size 4, int32 user IDを確認して完了する.
        """
        payload = pystruct.pack("<i", 100)
        result = write_packet(ServerPacketID.LOGIN_REPLY, payload)
        expected = b"\x05\x00\x00\x04\x00\x00\x00\x64\x00\x00\x00"
        assert result == expected

    def test_channel_info_complete_packet(self) -> None:
        """空payloadのCHANNEL_INFO_COMPLETEの既知wire bytesを検証する.

        Returns:
            None: packet ID 89とpayload size 0の7 byte headerを確認して完了する.
        """
        result = write_packet(ServerPacketID.CHANNEL_INFO_COMPLETE, b"")
        expected = b"\x59\x00\x00\x00\x00\x00\x00"
        assert result == expected


class TestWritePacketDefaultPayload:
    """write_packetの既定empty payload contractを検証する."""

    def test_default_payload_is_empty(self) -> None:
        """payloadを省略したpacketが空payloadとして書き込まれることを検証する.

        Returns:
            None: 7 byte packetとcontent size 0を確認して完了する.
        """
        result = write_packet(ServerPacketID.PING)
        assert len(result) == BANCHO_PACKET_HEADER_SIZE
        content_size = cast("int", pystruct.unpack_from("<I", result, 3)[0])
        assert content_size == 0


class TestQuietS2cPackets:
    """QUIET_S2C_PACKETSの静音packet集合contractを検証する."""

    def test_contains_ping(self) -> None:
        """PINGがquiet S2C packet集合へ含まれることを検証する.

        Returns:
            None: PINGの集合membershipを確認して完了する.
        """
        assert ServerPacketID.PING in QUIET_S2C_PACKETS

    def test_contains_user_stats(self) -> None:
        """USER_STATSがquiet S2C packet集合へ含まれることを検証する.

        Returns:
            None: USER_STATSの集合membershipを確認して完了する.
        """
        assert ServerPacketID.USER_STATS in QUIET_S2C_PACKETS

    def test_contains_user_presence(self) -> None:
        """USER_PRESENCEがquiet S2C packet集合へ含まれることを検証する.

        Returns:
            None: USER_PRESENCEの集合membershipを確認して完了する.
        """
        assert ServerPacketID.USER_PRESENCE in QUIET_S2C_PACKETS

    def test_is_frozenset(self) -> None:
        """Quiet S2C packet集合がimmutableなfrozensetであることを検証する.

        Returns:
            None: 集合のruntime typeを確認して完了する.
        """
        assert isinstance(QUIET_S2C_PACKETS, frozenset)


class TestWritePacketLogging:
    """write_packetのS2C packet logging contractを検証する."""

    def test_normal_packet_logged_at_info(self) -> None:
        """non-quiet packetがnameとpayload sizeをINFOで記録することを検証する.

        Returns:
            None: LOGIN_REPLYのs2c_packet event, info level, packet名, sizeを確認して完了する.
        """
        payload = b"\x01\x02\x03"
        with structlog.testing.capture_logs() as logs:
            _ = write_packet(ServerPacketID.LOGIN_REPLY, payload)

        s2c_logs = [log for log in logs if log["event"] == "s2c_packet"]
        assert len(s2c_logs) == 1
        assert s2c_logs[0]["log_level"] == "info"
        assert s2c_logs[0]["packet"] == "LOGIN_REPLY"
        assert s2c_logs[0]["size"] == len(payload)

    def test_quiet_packet_logged_at_debug(self) -> None:
        """Quiet packetがnameとpayload sizeをDEBUGで記録することを検証する.

        Returns:
            None: PINGのs2c_packet event, debug level, packet名, size 0を確認して完了する.
        """
        with structlog.testing.capture_logs() as logs:
            _ = write_packet(ServerPacketID.PING, b"")

        s2c_logs = [log for log in logs if log["event"] == "s2c_packet"]
        assert len(s2c_logs) == 1
        assert s2c_logs[0]["log_level"] == "debug"
        assert s2c_logs[0]["packet"] == "PING"
        assert s2c_logs[0]["size"] == 0

    def test_all_quiet_packets_logged_at_debug(self) -> None:
        """すべてのquiet packetがDEBUGだけで記録されることを検証する.

        Returns:
            None: 各QUIET_S2C_PACKETS memberの単一debug eventを確認して完了する.
        """
        for packet_id in QUIET_S2C_PACKETS:
            with structlog.testing.capture_logs() as logs:
                _ = write_packet(packet_id, b"\xaa")

            s2c_logs = [log for log in logs if log["event"] == "s2c_packet"]
            assert len(s2c_logs) == 1, f"{packet_id.name} should produce exactly 1 log"
            assert s2c_logs[0]["log_level"] == "debug", (
                f"{packet_id.name} should be logged at debug"
            )

    def test_size_reflects_payload_not_total(self) -> None:
        """記録するsizeがheaderを含まないpayload長であることを検証する.

        Returns:
            None: SEND_MESSAGE eventのsizeが5 byte payload長と一致することを確認して完了する.
        """
        payload = b"\x01\x02\x03\x04\x05"
        with structlog.testing.capture_logs() as logs:
            _ = write_packet(ServerPacketID.SEND_MESSAGE, payload)

        s2c_logs = [log for log in logs if log["event"] == "s2c_packet"]
        assert s2c_logs[0]["size"] == len(payload)  # payload size, not header + payload

    def test_logging_does_not_alter_packet_bytes(self) -> None:
        """loggingを有効にしてもpacket wire bytesが変化しないことを検証する.

        Returns:
            None: LOGIN_REPLYのheaderとpayloadが既知bytesと一致することを確認して完了する.
        """
        payload = b"\xde\xad"
        with structlog.testing.capture_logs():
            result = write_packet(ServerPacketID.LOGIN_REPLY, payload)

        expected = pystruct.pack("<HBI", ServerPacketID.LOGIN_REPLY, 0, 2) + payload
        assert result == expected

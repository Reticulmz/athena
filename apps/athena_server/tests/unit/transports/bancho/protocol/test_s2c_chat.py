"""S2C chat packet builderのwire contractを検証する."""

import struct as pystruct
from typing import cast

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.chat import (
    channel_join_success,
    channel_revoked,
    send_message,
    user_dm_blocked,
)


def _extract_packet_id(data: bytes) -> int:
    """Bancho packet header先頭のlittle-endian ServerPacketIDを取得する.

    Args:
        data (bytes): 先頭2 byteにpacket IDを持つBancho packet.

    Returns:
        int: headerから復元したServerPacketIDの整数値.

    Notes:
        呼び出し側は少なくとも2 byteのpacketを渡すこと.
    """
    return cast("int", pystruct.unpack_from("<H", data, 0)[0])


def _extract_payload(data: bytes) -> bytes:
    """7 byte Bancho headerの後ろにあるpayloadを取得する.

    Args:
        data (bytes): headerとpayloadを連結したBancho packet.

    Returns:
        bytes: offset 7以降の未加工payload.

    Notes:
        呼び出し側は標準の7 byte headerを含むpacketを渡すこと.
    """
    return data[7:]


def _extract_payload_size(data: bytes) -> int:
    """Bancho header bytes 3-6から宣言済みpayload sizeを取得する.

    Args:
        data (bytes): size fieldを含むBancho packet header.

    Returns:
        int: little-endian uint32として復元したpayload size.

    Notes:
        呼び出し側は少なくとも7 byteのpacketを渡すこと.
    """
    return cast("int", pystruct.unpack_from("<I", data, 3)[0])


class TestSendMessage:
    """SEND_MESSAGE packetのMessage payload contractを検証する."""

    def test_packet_id(self) -> None:
        """send_messageがSEND_MESSAGEのpacket IDをheaderへ書く契約を検証する.

        Returns:
            None: headerのpacket IDを検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        assert _extract_packet_id(pkt) == ServerPacketID.SEND_MESSAGE

    def test_payload_contains_sender(self) -> None:
        """send_messageが指定senderをMessage payloadへ保持する契約を検証する.

        Returns:
            None: sender bytesの存在を検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        payload = _extract_payload(pkt)
        assert b"TestUser" in payload

    def test_payload_contains_content(self) -> None:
        """send_messageが指定contentをMessage payloadへ保持する契約を検証する.

        Returns:
            None: content bytesの存在を検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = send_message(sender="TestUser", content="hello world", target="#osu", sender_id=42)
        payload = _extract_payload(pkt)
        assert b"hello world" in payload

    def test_payload_contains_target(self) -> None:
        """send_messageが指定targetをMessage payloadへ保持する契約を検証する.

        Returns:
            None: target bytesの存在を検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        payload = _extract_payload(pkt)
        assert b"#osu" in payload

    def test_payload_contains_sender_id(self) -> None:
        """send_messageがsender_idを末尾のsigned int32として書く契約を検証する.

        Returns:
            None: sender IDのwire値を検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        payload = _extract_payload(pkt)
        # sender_id is the last 4 bytes as int32
        sender_id = cast("int", pystruct.unpack_from("<i", payload, len(payload) - 4)[0])
        assert sender_id == 42

    def test_payload_size_matches_header(self) -> None:
        """send_messageのheader sizeが実際のpayload lengthと一致する契約を検証する.

        Returns:
            None: 宣言値と実測値を検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = send_message(sender="TestUser", content="hello", target="#osu", sender_id=42)
        declared = _extract_payload_size(pkt)
        actual = len(_extract_payload(pkt))
        assert declared == actual

    def test_returns_bytes(self) -> None:
        """send_messageが送信可能なbytes packetを返す契約を検証する.

        Returns:
            None: 戻り値の型を検証して完了し, 呼び出し側へ値を返さない.
        """
        result = send_message(sender="A", content="B", target="#c", sender_id=1)
        assert isinstance(result, bytes)


class TestChannelJoinSuccess:
    """CHANNEL_JOIN_SUCCESS packetのBanchoString payload contractを検証する."""

    def test_packet_id(self) -> None:
        """channel_join_successが成功通知のpacket IDをheaderへ書く契約を検証する.

        Returns:
            None: headerのpacket IDを検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = channel_join_success(channel_name="#osu")
        assert _extract_packet_id(pkt) == ServerPacketID.CHANNEL_JOIN_SUCCESS

    def test_payload_contains_channel_name(self) -> None:
        """channel_join_successがchannel nameをpayloadへ保持する契約を検証する.

        Returns:
            None: channel name bytesを検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = channel_join_success(channel_name="#osu")
        payload = _extract_payload(pkt)
        assert b"#osu" in payload

    def test_payload_size_matches_header(self) -> None:
        """channel_join_successのheader sizeがpayload lengthと一致する契約を検証する.

        Returns:
            None: 宣言値と実測値を検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = channel_join_success(channel_name="#osu")
        declared = _extract_payload_size(pkt)
        actual = len(_extract_payload(pkt))
        assert declared == actual


class TestChannelRevoked:
    """CHANNEL_REVOKED packetのBanchoString payload contractを検証する."""

    def test_packet_id(self) -> None:
        """channel_revokedが取消通知のpacket IDをheaderへ書く契約を検証する.

        Returns:
            None: headerのpacket IDを検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = channel_revoked(channel_name="#osu")
        assert _extract_packet_id(pkt) == ServerPacketID.CHANNEL_REVOKED

    def test_payload_contains_channel_name(self) -> None:
        """channel_revokedがchannel nameをpayloadへ保持する契約を検証する.

        Returns:
            None: channel name bytesを検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = channel_revoked(channel_name="#osu")
        payload = _extract_payload(pkt)
        assert b"#osu" in payload

    def test_payload_size_matches_header(self) -> None:
        """channel_revokedのheader sizeがpayload lengthと一致する契約を検証する.

        Returns:
            None: 宣言値と実測値を検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = channel_revoked(channel_name="#osu")
        declared = _extract_payload_size(pkt)
        actual = len(_extract_payload(pkt))
        assert declared == actual


class TestUserDmBlocked:
    """USER_DM_BLOCKED packetの空sender Message payload contractを検証する."""

    def test_packet_id(self) -> None:
        """user_dm_blockedがUSER_DM_BLOCKEDのpacket IDをheaderへ書く契約を検証する.

        Returns:
            None: headerのpacket IDを検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = user_dm_blocked(target="target")
        assert _extract_packet_id(pkt) == ServerPacketID.USER_DM_BLOCKED

    def test_payload_contains_target_only_and_zero_sender_id(self) -> None:
        """user_dm_blockedがtargetだけとsender_id=0をpayloadへ書く契約を検証する.

        Returns:
            None: target, BanchoBot不在, sender IDを検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = user_dm_blocked(target="target")
        payload = _extract_payload(pkt)

        assert b"target" in payload
        assert b"BanchoBot" not in payload
        sender_id = cast("int", pystruct.unpack_from("<i", payload, len(payload) - 4)[0])
        assert sender_id == 0

    def test_payload_size_matches_header(self) -> None:
        """user_dm_blockedのheader sizeがpayload lengthと一致する契約を検証する.

        Returns:
            None: 宣言値と実測値を検証して完了し, 呼び出し側へ値を返さない.
        """
        pkt = user_dm_blocked(target="target")
        declared = _extract_payload_size(pkt)
        actual = len(_extract_payload(pkt))
        assert declared == actual

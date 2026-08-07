"""USER_PRESENCEとUSER_PRESENCE_BUNDLEのgolden bytes contractを検証する."""

from __future__ import annotations

import struct as pystruct
from dataclasses import dataclass
from io import BytesIO
from typing import cast

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    user_presence,
    user_presence_bundle,
)


@dataclass(frozen=True, slots=True)
class _DecodedPresence:
    """fixture payloadから復元したUSER_PRESENCE field値を保持する.

    Attributes:
        user_id (int): signed int32として復元したstable user ID.
        username (str): BanchoStringから復元した表示名.
        timezone (int): uint8 timezone offset値.
        country_id (int): uint8 country ID.
        permissions_mode (int): permissionとmodeを合成したuint8値.
        longitude (float): float32として復元したlongitude.
        latitude (float): float32として復元したlatitude.
        rank (int): signed int32として復元したglobal rank.
    """

    user_id: int
    username: str
    timezone: int
    country_id: int
    permissions_mode: int
    longitude: float
    latitude: float
    rank: int


def _read_exact(stream: BytesIO, size: int) -> bytes:
    """streamから指定sizeのbytesを完全に読み取る.

    Args:
        stream (BytesIO): 読み取り位置を進めるfixture payload stream.
        size (int): 取得するbyte数.

    Returns:
        bytes: streamから取得したsize byteの値.

    Notes:
        streamの残りがsize byte未満ならassertionでfixtureの不完全さを検出する.
    """
    data = stream.read(size)
    assert len(data) == size
    return data


def _read_i32(stream: BytesIO) -> int:
    """stream先頭からlittle-endian signed int32を読み取る.

    Args:
        stream (BytesIO): signed int32が現在位置にあるfixture payload stream.

    Returns:
        int: 4 byteから復元したsigned int32値.
    """
    return cast("int", pystruct.unpack("<i", _read_exact(stream, 4))[0])


def _read_u16(stream: BytesIO) -> int:
    """stream先頭からlittle-endian uint16を読み取る.

    Args:
        stream (BytesIO): uint16が現在位置にあるfixture payload stream.

    Returns:
        int: 2 byteから復元したuint16値.
    """
    return cast("int", pystruct.unpack("<H", _read_exact(stream, 2))[0])


def _read_u8(stream: BytesIO) -> int:
    """stream先頭からuint8を読み取る.

    Args:
        stream (BytesIO): uint8が現在位置にあるfixture payload stream.

    Returns:
        int: 1 byteから復元したuint8値.
    """
    return _read_exact(stream, 1)[0]


def _read_f32(stream: BytesIO) -> float:
    """stream先頭からlittle-endian float32を読み取る.

    Args:
        stream (BytesIO): float32が現在位置にあるfixture payload stream.

    Returns:
        float: 4 byteから復元したfloat32値.
    """
    return cast("float", pystruct.unpack("<f", _read_exact(stream, 4))[0])


def _read_string(stream: BytesIO) -> str:
    """stream先頭からBanchoStringを読み取る.

    Args:
        stream (BytesIO): BanchoString markerが現在位置にあるfixture payload stream.

    Returns:
        str: empty markerまたはUTF-8 bytesから復元した文字列.

    Notes:
        marker 0は空文字列, marker 0x0Bは後続uint8 lengthのUTF-8 textを表す.
    """
    marker = _read_u8(stream)
    if marker == 0:
        return ""
    assert marker == 0x0B

    length = _read_u8(stream)
    return _read_exact(stream, length).decode("utf-8")


def _decode_presence(payload: bytes) -> _DecodedPresence:
    """USER_PRESENCE payloadをfixture用のfield値へdecodeする.

    Args:
        payload (bytes): 7 byte packet headerを除いたUSER_PRESENCE payload.

    Returns:
        _DecodedPresence: wire順に復元したpresence field値.

    Notes:
        全fieldを読み取った後に余剰bytesがないことをassertionで検証する.
    """
    stream = BytesIO(payload)
    result = _DecodedPresence(
        user_id=_read_i32(stream),
        username=_read_string(stream),
        timezone=_read_u8(stream),
        country_id=_read_u8(stream),
        permissions_mode=_read_u8(stream),
        longitude=_read_f32(stream),
        latitude=_read_f32(stream),
        rank=_read_i32(stream),
    )
    assert stream.read() == b""
    return result


def _decode_int_list(payload: bytes) -> list[int]:
    """count-prefixed signed int32 list payloadをdecodeする.

    Args:
        payload (bytes): uint16 countとsigned int32要素を持つpayload.

    Returns:
        list[int]: wire順に復元した整数値の一覧.

    Notes:
        count件の要素を読んだ後に余剰bytesがないことをassertionで検証する.
    """
    stream = BytesIO(payload)
    count = _read_u16(stream)
    result = [_read_i32(stream) for _ in range(count)]
    assert stream.read() == b""
    return result


def _payload(packet: bytes) -> bytes:
    """Bancho packetから7 byte headerを除いたpayloadを取得する.

    Args:
        packet (bytes): 標準headerとpayloadを連結したBancho packet.

    Returns:
        bytes: offset 7以降の未加工payload.
    """
    return packet[7:]


def _packet_id(packet: bytes) -> int:
    """Bancho packet headerからlittle-endian ServerPacketIDを取得する.

    Args:
        packet (bytes): 先頭2 byteにpacket IDを持つBancho packet.

    Returns:
        int: headerから復元したServerPacketIDの整数値.
    """
    return cast("int", pystruct.unpack_from("<H", packet, 0)[0])


def test_user_presence_packet_id() -> None:
    """user_presenceがUSER_PRESENCEのpacket IDをheaderへ書く契約を検証する.

    Returns:
        None: headerのpacket IDを検証して完了し, 呼び出し側へ値を返さない.
    """
    packet = user_presence(
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

    assert _packet_id(packet) == ServerPacketID.USER_PRESENCE


def test_user_presence_payload_matches_golden_bytes_and_decodes() -> None:
    """通常userのUSER_PRESENCE payloadがgolden bytesとdecode結果を保持する契約を検証する.

    Returns:
        None: exact payloadと各fieldの復元値を検証して完了し, 呼び出し側へ値を返さない.
    """
    expected = (
        b"\x2a\x00\x00\x00\x0b\x04user\x18\x01\x70\x00\xc0\x0b\x43\x00\x00\x0e\x42\x64\x00\x00\x00"
    )

    payload = _payload(
        user_presence(
            user_id=42,
            username="user",
            timezone=24,
            country_id=1,
            permissions=16,
            mode=3,
            longitude=139.75,
            latitude=35.5,
            rank=100,
        )
    )

    assert payload == expected
    decoded = _decode_presence(expected)
    assert decoded == _DecodedPresence(
        user_id=42,
        username="user",
        timezone=24,
        country_id=1,
        permissions_mode=112,
        longitude=139.75,
        latitude=35.5,
        rank=100,
    )


def test_banchobot_user_presence_payload_matches_golden_bytes_and_decodes() -> None:
    """BanchoBotのzero-valued presence payloadがgolden bytesと一致する契約を検証する.

    Returns:
        None: exact payloadとBanchoBot field値を検証して完了し, 呼び出し側へ値を返さない.
    """
    expected = (
        b"\x01\x00\x00\x00"
        b"\x0b\x09BanchoBot"
        b"\x18\x00\x10"
        b"\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
    )

    payload = _payload(
        user_presence(
            user_id=1,
            username="BanchoBot",
            timezone=24,
            country_id=0,
            permissions=16,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
    )

    assert payload == expected
    decoded = _decode_presence(expected)
    assert decoded == _DecodedPresence(
        user_id=1,
        username="BanchoBot",
        timezone=24,
        country_id=0,
        permissions_mode=16,
        longitude=0.0,
        latitude=0.0,
        rank=0,
    )


def test_user_presence_bundle_payload_matches_golden_bytes_and_decodes() -> None:
    """user_presence_bundleがcount-prefixed user IDのgolden bytesを作る契約を検証する.

    Returns:
        None: exact payloadとwire順のuser ID一覧を検証して完了し, 呼び出し側へ値を返さない.
    """
    expected = b"\x03\x00\x01\x00\x00\x00\x2a\x00\x00\x00\x64\x00\x00\x00"

    payload = _payload(user_presence_bundle([1, 42, 100]))

    assert payload == expected
    assert _decode_int_list(expected) == [1, 42, 100]


def test_user_presence_bundle_packet_id() -> None:
    """user_presence_bundleがUSER_PRESENCE_BUNDLEのpacket IDをheaderへ書く契約を検証する.

    Returns:
        None: headerのpacket IDを検証して完了し, 呼び出し側へ値を返さない.
    """
    packet = user_presence_bundle([5, 10])

    assert _packet_id(packet) == ServerPacketID.USER_PRESENCE_BUNDLE

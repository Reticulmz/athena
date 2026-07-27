"""USER_STATSとStatusUpdateのgolden bytes contractを検証する."""

from __future__ import annotations

import struct as pystruct
from dataclasses import dataclass
from io import BytesIO
from typing import cast

from osu_server.transports.stable.bancho.protocol.c2s import (
    parse_status_change_payload,
    status_change_payload,
)
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats
from osu_server.transports.stable.bancho.protocol.types import StatusUpdate


@dataclass(frozen=True, slots=True)
class _DecodedStatusUpdate:
    """fixture payloadから復元したStatusUpdate field値を保持する.

    Attributes:
        status (int): uint8として復元したstatus wire値.
        status_text (str): BanchoStringから復元したstatus text.
        beatmap_md5 (str): BanchoStringから復元したcurrent beatmap MD5.
        mods (int): signed int32として復元したmods bitmask.
        play_mode (int): uint8として復元したstable play mode.
        beatmap_id (int): signed int32として復元したcurrent beatmap ID.
    """

    status: int
    status_text: str
    beatmap_md5: str
    mods: int
    play_mode: int
    beatmap_id: int


@dataclass(frozen=True, slots=True)
class _DecodedStats:
    """fixture payloadから復元したUSER_STATS field値を保持する.

    Attributes:
        user_id (int): signed int32として復元したstable user ID.
        status_update (_DecodedStatusUpdate): nested StatusUpdateの復元値.
        ranked_score (int): signed int64として復元したranked score.
        accuracy (float): float32として復元したaccuracy ratio.
        play_count (int): signed int32として復元したplay count.
        total_score (int): signed int64として復元したtotal score.
        rank (int): signed int32として復元したglobal rank.
        pp (int): uint16として復元したperformance point.
    """

    user_id: int
    status_update: _DecodedStatusUpdate
    ranked_score: int
    accuracy: float
    play_count: int
    total_score: int
    rank: int
    pp: int


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


def _read_i64(stream: BytesIO) -> int:
    """stream先頭からlittle-endian signed int64を読み取る.

    Args:
        stream (BytesIO): signed int64が現在位置にあるfixture payload stream.

    Returns:
        int: 8 byteから復元したsigned int64値.
    """
    return cast("int", pystruct.unpack("<q", _read_exact(stream, 8))[0])


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


def _read_status_update(stream: BytesIO) -> _DecodedStatusUpdate:
    """stream先頭からStatusUpdate field群を読み取る.

    Args:
        stream (BytesIO): StatusUpdateが現在位置にあるfixture payload stream.

    Returns:
        _DecodedStatusUpdate: wire順に復元したstatus, strings, mods, mode, beatmap ID.
    """
    return _DecodedStatusUpdate(
        status=_read_u8(stream),
        status_text=_read_string(stream),
        beatmap_md5=_read_string(stream),
        mods=_read_i32(stream),
        play_mode=_read_u8(stream),
        beatmap_id=_read_i32(stream),
    )


def _decode_stats(payload: bytes) -> _DecodedStats:
    """USER_STATS payloadをfixture用のfield値へdecodeする.

    Args:
        payload (bytes): 7 byte packet headerを除いたUSER_STATS payload.

    Returns:
        _DecodedStats: wire順に復元したstats field値.

    Notes:
        全fieldを読み取った後に余剰bytesがないことをassertionで検証する.
    """
    stream = BytesIO(payload)
    result = _DecodedStats(
        user_id=_read_i32(stream),
        status_update=_read_status_update(stream),
        ranked_score=_read_i64(stream),
        accuracy=_read_f32(stream),
        play_count=_read_i32(stream),
        total_score=_read_i64(stream),
        rank=_read_i32(stream),
        pp=_read_u16(stream),
    )
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


def test_user_stats_packet_id() -> None:
    """user_statsがUSER_STATSのpacket IDをheaderへ書く契約を検証する.

    Returns:
        None: headerのpacket IDを検証して完了し, 呼び出し側へ値を返さない.
    """
    packet = user_stats(
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

    assert _packet_id(packet) == ServerPacketID.USER_STATS


def test_user_stats_payload_matches_golden_bytes_and_decodes() -> None:
    """通常userのUSER_STATS payloadがgolden bytesとdecode結果を保持する契約を検証する.

    Returns:
        None: exact payloadと全stats fieldの復元値を検証して完了し, 呼び出し側へ値を返さない.
    """
    expected = (
        b"\x2a\x00\x00\x00"
        b"\x02"
        b"\x0b\x07Playing"
        b"\x0b\x20"
        b"3b0aecd99eba50ffc7bff8da117d0e06"
        b"\x18\x00\x00\x00"
        b"\x00"
        b"\xd2\x04\x00\x00"
        b"\x15\xcd\x5b\x07\x00\x00\x00\x00"
        b"\xf6\x28\x7c\x3f"
        b"\x41\x01\x00\x00"
        b"\xea\x16\xb0\x4c\x02\x00\x00\x00"
        b"\x4d\x00\x00\x00"
        b"\x31\xd4"
    )

    payload = _payload(
        user_stats(
            user_id=42,
            status=2,
            status_text="Playing",
            beatmap_md5="3b0aecd99eba50ffc7bff8da117d0e06",
            mods=24,
            play_mode=0,
            beatmap_id=1234,
            ranked_score=123456789,
            accuracy=0.985,
            play_count=321,
            total_score=9876543210,
            rank=77,
            pp=54321,
        )
    )

    assert payload == expected
    decoded = _decode_stats(expected)
    assert decoded.user_id == 42
    assert decoded.status_update == _DecodedStatusUpdate(
        status=2,
        status_text="Playing",
        beatmap_md5="3b0aecd99eba50ffc7bff8da117d0e06",
        mods=24,
        play_mode=0,
        beatmap_id=1234,
    )
    assert decoded.ranked_score == 123456789
    assert abs(decoded.accuracy - 0.985) < 0.000001
    assert decoded.play_count == 321
    assert decoded.total_score == 9876543210
    assert decoded.rank == 77
    assert decoded.pp == 54321


def test_user_stats_clamps_pp_to_uint16_max() -> None:
    """user_statsがuint16上限超過ppを65535へclampする契約を検証する.

    Returns:
        None: payload末尾とdecode後ppの上限値を検証して完了し, 呼び出し側へ値を返さない.
    """
    payload = _payload(
        user_stats(
            user_id=42,
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
            pp=70000,
        )
    )

    assert payload[-2:] == b"\xff\xff"
    assert _decode_stats(payload).pp == 65535


def test_banchobot_user_stats_payload_matches_golden_bytes_and_decodes() -> None:
    """BanchoBotのzero-valued stats payloadがgolden bytesと一致する契約を検証する.

    Returns:
        None: exact payloadとBanchoBot stats field値を検証して完了し, 呼び出し側へ値を返さない.
    """
    expected = (
        b"\x01\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00"
        b"\x00\x00"
    )

    payload = _payload(
        user_stats(
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
    )

    assert payload == expected
    decoded = _decode_stats(expected)
    assert decoded == _DecodedStats(
        user_id=1,
        status_update=_DecodedStatusUpdate(
            status=0,
            status_text="",
            beatmap_md5="",
            mods=0,
            play_mode=0,
            beatmap_id=0,
        ),
        ranked_score=0,
        accuracy=0.0,
        play_count=0,
        total_score=0,
        rank=0,
        pp=0,
    )


def test_status_change_payload_matches_golden_bytes_and_decodes_empty_strings() -> None:
    """空のStatusUpdateがC2S status changeのgolden bytesへround-tripする契約を検証する.

    Returns:
        None: exact payloadとparse後のempty field値を検証して完了し, 呼び出し側へ値を返さない.
    """
    expected = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    status_update = StatusUpdate(
        status=0,
        status_text="",
        beatmap_md5="",
        mods=0,
        play_mode=0,
        beatmap_id=0,
    )

    assert status_change_payload(status_update) == expected

    decoded = parse_status_change_payload(expected)
    assert decoded.status == 0
    assert decoded.status_text == ""
    assert decoded.beatmap_md5 == ""
    assert decoded.mods == 0
    assert decoded.play_mode == 0
    assert decoded.beatmap_id == 0

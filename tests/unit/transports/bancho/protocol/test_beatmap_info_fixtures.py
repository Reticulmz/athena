"""BEATMAP_INFO の独立 golden payload を検証する.

Lekuruu bancho-documentation wiki revision
`7c177543497beacf443b6fecd3f52045c6cf1c5c` を primary evidence とし,
Lekuruu/chio.py@`9d2391a5b2d3610d72e2e794d0749a00329286c1` と
osuTitanic/anchor@`b19d14ccdcdf157026c257586faf49bf4542971e` の binary flow を
positive crosscheck とする. 対象は現行 4-Grade layout のみであり, Target packet
capture は未取得である.

各 fixed payload literal は evidence の field layout から field segment ごとに
手作業で導出したものである. production serializer, `pack` の出力, fixture
generation script のいずれからも生成していない. `pack` は encoder under test,
`unpack` は decoder under test としてのみ使用する.
"""

from caterpillar.model import pack, unpack

from osu_server.domain.compatibility.stable.grade import StableGrade
from osu_server.transports.stable.bancho.protocol.c2s import BeatmapInfoRequest
from osu_server.transports.stable.bancho.protocol.s2c.beatmap_info import (
    BeatmapInfo,
    BeatmapInfoReply,
)


def _canonical_request() -> BeatmapInfoRequest:
    """mixed filename / ID request の typed canonical value を返す.

    Returns:
        BeatmapInfoRequest: filename 2件と beatmap ID 2件を入力順で持つ request.

    Raises:
        None: typed value の構築だけを行うため, 通常は例外を送出しない.

    Notes:
        この helper は fixture bytes を構築しない. bytes literal は各 test 内で
        fixed evidence として直接記述する.
    """
    return BeatmapInfoRequest(
        filename_count=2,
        filenames=["alpha.osu", "beta.osu"],
        id_count=2,
        beatmap_ids=[12_345, 67_890],
    )


def _canonical_reply() -> BeatmapInfoReply:
    """filename row と ID row を持つ typed canonical reply を返す.

    Returns:
        BeatmapInfoReply: request index 1 の filename row と index -1 の ID row を
            入力順で持つ 2 row reply.

    Raises:
        None: typed value の構築だけを行うため, 通常は例外を送出しない.

    Notes:
        この helper は fixture bytes を構築しない. row の grade は mode field
        swap を検出できるよう相互に異なる StableGrade member を使う.
    """
    return BeatmapInfoReply(
        count=2,
        beatmaps=[
            BeatmapInfo(
                request_index=1,
                beatmap_id=12_345,
                beatmapset_id=23_456,
                thread_id=34_567,
                ranked=2,
                osu_grade=StableGrade.XH,
                fruits_grade=StableGrade.S,
                taiko_grade=StableGrade.B,
                mania_grade=StableGrade.N,
                md5="0123456789abcdef0123456789abcdef",
            ),
            BeatmapInfo(
                request_index=-1,
                beatmap_id=67_890,
                beatmapset_id=78_901,
                thread_id=89_012,
                ranked=1,
                osu_grade=StableGrade.SH,
                fruits_grade=StableGrade.A,
                taiko_grade=StableGrade.C,
                mania_grade=StableGrade.F,
                md5="fedcba9876543210fedcba9876543210",
            ),
        ],
    )


def test_beatmap_info_request_matches_independent_golden_payload_and_decodes() -> None:
    """mixed request が fixed payload と一致し, list順序を復元することを検証する.

    Returns:
        None: encoder と decoder の contract assertion が成立したことを示す.

    Raises:
        AssertionError: request field順序, count, または list値が canonical evidence と
            一致しない場合.

    Notes:
        expected_payload は production encoder から生成せず, fixed revision evidence の
        field layout に従う独立 literal である.
    """
    expected_payload = (
        # filename_count: signed i32 little-endian で 2件.
        b"\x02\x00\x00\x00"
        # filenames[0]: BanchoString "alpha.osu".
        b"\x0b\x09alpha.osu"
        # filenames[1]: BanchoString "beta.osu".
        b"\x0b\x08beta.osu"
        # id_count: signed i32 little-endian で 2件.
        b"\x02\x00\x00\x00"
        # beatmap_ids[0]: signed i32 little-endian で 12345.
        b"\x39\x30\x00\x00"
        # beatmap_ids[1]: signed i32 little-endian で 67890.
        b"\x32\x09\x01\x00"
    )

    request = _canonical_request()

    assert pack(request) == expected_payload

    decoded = unpack(BeatmapInfoRequest, expected_payload)

    assert decoded.filename_count == 2
    assert decoded.filenames == ["alpha.osu", "beta.osu"]
    assert decoded.id_count == 2
    assert decoded.beatmap_ids == [12_345, 67_890]


def test_beatmap_info_request_empty_collection_matches_isolated_golden_payload() -> None:
    """empty request が 8 zero bytes として pack / unpack されることを検証する.

    Returns:
        None: empty collection の固定境界 assertion が成立したことを示す.

    Raises:
        AssertionError: empty request の count field または collection が canonical
            boundary と一致しない場合.

    Notes:
        canonical mixed request と分離し, filename_count と id_count の field境界だけを
        検証する.
    """
    expected_payload = b"\x00\x00\x00\x00\x00\x00\x00\x00"
    request = BeatmapInfoRequest(
        filename_count=0,
        filenames=[],
        id_count=0,
        beatmap_ids=[],
    )

    assert pack(request) == expected_payload

    decoded = unpack(BeatmapInfoRequest, expected_payload)

    assert decoded.filename_count == 0
    assert decoded.filenames == []
    assert decoded.id_count == 0
    assert decoded.beatmap_ids == []


def test_beatmap_info_reply_matches_independent_golden_payload_and_decodes() -> None:
    """2 row reply が fixed payload と一致し, 全 field を typed に復元することを検証する.

    Returns:
        None: encoder と decoder の contract assertion が成立したことを示す.

    Raises:
        AssertionError: reply count, row順序, field値, または StableGrade member が
            canonical evidence と一致しない場合.

    Notes:
        expected_payload は production encoder から生成せず, fixed revision evidence の
        field layout に従う独立 literal である.
    """
    expected_payload = (
        # count: signed i32 little-endian で 2 row.
        b"\x02\x00\x00\x00"
        # row 1 request_index: signed i16 little-endian で filename index 1.
        b"\x01\x00"
        # row 1 beatmap_id: signed i32 little-endian で 12345.
        b"\x39\x30\x00\x00"
        # row 1 beatmapset_id: signed i32 little-endian で 23456.
        b"\xa0\x5b\x00\x00"
        # row 1 thread_id: signed i32 little-endian で 34567.
        b"\x07\x87\x00\x00"
        # row 1 ranked: signed i8 で 2.
        b"\x02"
        # row 1 grades: osu XH, fruits S, taiko B, mania N.
        b"\x00\x03\x05\x09"
        # row 1 md5: 32文字 BanchoString.
        b"\x0b\x20"
        b"0123456789abcdef0123456789abcdef"
        # row 2 request_index: signed i16 little-endian で ID request の -1.
        b"\xff\xff"
        # row 2 beatmap_id: signed i32 little-endian で 67890.
        b"\x32\x09\x01\x00"
        # row 2 beatmapset_id: signed i32 little-endian で 78901.
        b"\x35\x34\x01\x00"
        # row 2 thread_id: signed i32 little-endian で 89012.
        b"\xb4\x5b\x01\x00"
        # row 2 ranked: signed i8 で 1.
        b"\x01"
        # row 2 grades: osu SH, fruits A, taiko C, mania F.
        b"\x01\x04\x06\x08"
        # row 2 md5: 32文字 BanchoString.
        b"\x0b\x20"
        b"fedcba9876543210fedcba9876543210"
    )

    reply = _canonical_reply()

    assert pack(reply) == expected_payload

    decoded = unpack(BeatmapInfoReply, expected_payload)

    assert decoded.count == 2
    assert len(decoded.beatmaps) == decoded.count

    filename_row, id_row = decoded.beatmaps

    assert filename_row.request_index == 1
    assert filename_row.beatmap_id == 12_345
    assert filename_row.beatmapset_id == 23_456
    assert filename_row.thread_id == 34_567
    assert filename_row.ranked == 2
    assert filename_row.osu_grade is StableGrade.XH
    assert filename_row.fruits_grade is StableGrade.S
    assert filename_row.taiko_grade is StableGrade.B
    assert filename_row.mania_grade is StableGrade.N
    assert filename_row.md5 == "0123456789abcdef0123456789abcdef"

    assert id_row.request_index == -1
    assert id_row.beatmap_id == 67_890
    assert id_row.beatmapset_id == 78_901
    assert id_row.thread_id == 89_012
    assert id_row.ranked == 1
    assert id_row.osu_grade is StableGrade.SH
    assert id_row.fruits_grade is StableGrade.A
    assert id_row.taiko_grade is StableGrade.C
    assert id_row.mania_grade is StableGrade.F
    assert id_row.md5 == "fedcba9876543210fedcba9876543210"


def test_beatmap_info_reply_empty_collection_matches_isolated_golden_payload() -> None:
    """empty reply が 4 zero bytes として pack / unpack されることを検証する.

    Returns:
        None: empty collection の固定境界 assertion が成立したことを示す.

    Raises:
        AssertionError: empty reply の count field または row collection が canonical
            boundary と一致しない場合.

    Notes:
        canonical 2 row reply と分離し, count field だけを検証する.
    """
    expected_payload = b"\x00\x00\x00\x00"
    reply = BeatmapInfoReply(count=0, beatmaps=[])

    assert pack(reply) == expected_payload

    decoded = unpack(BeatmapInfoReply, expected_payload)

    assert decoded.count == 0
    assert decoded.beatmaps == []

"""BeatmapInfo S2C reply wire struct の構造的な round-trip を検証する."""

from caterpillar.model import pack, unpack

from osu_server.domain.compatibility.stable.grade import StableGrade
from osu_server.transports.stable.bancho.protocol.s2c.beatmap_info import (
    BeatmapInfo,
    BeatmapInfoReply,
)


def _representative_reply() -> BeatmapInfoReply:
    """代表的なfilename rowとID rowを含むreplyを生成する.

    Returns:
        BeatmapInfoReply: filename requestのindex 1 rowと, ID requestのindex -1 rowを
            入力順に含むreply.

    Notes:
        このhelperはfixed golden bytesを生成せず, structのpack / unpack contractを
        検証するためのtyped valueだけを提供する.
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


def test_beatmap_info_reply_round_trips_ordered_rows_and_typed_grades() -> None:
    """2 row reply が request kind, field順序, typed grade を保持することを検証する.

    Returns:
        None: assertion がすべて成立したことを示す.

    Notes:
        filename request rowのrequest_index=1とID request rowのrequest_index=-1は
        structが保持するwire semanticsであり, このtestはindexの参照先妥当性を検証しない.
    """
    reply = _representative_reply()

    decoded = unpack(BeatmapInfoReply, pack(reply))

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


def test_beatmap_info_reply_round_trips_empty_collection() -> None:
    """空のreplyがrowを含まずcount 0として復元されることを検証する.

    Returns:
        None: assertionがすべて成立したことを示す.

    Notes:
        このtestはfixed golden bytesとの比較を行わず, counted collectionのstructural
        contractだけを検証する.
    """
    reply = BeatmapInfoReply(count=0, beatmaps=[])

    decoded = unpack(BeatmapInfoReply, pack(reply))

    assert decoded.count == 0
    assert decoded.beatmaps == []

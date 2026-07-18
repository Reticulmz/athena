"""BEATMAP_INFO_REPLY の S2C payload 定義."""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.fields import Enum, int8, int16, int32, uint8
from caterpillar.model import StructDefMixin
from caterpillar.model import struct as cpstruct

from osu_server.domain.compatibility.stable.grade import StableGrade
from osu_server.transports.stable.bancho.protocol.types import BanchoString


@cpstruct(order=LittleEndian)
class BeatmapInfo(StructDefMixin):
    """BEATMAP_INFO_REPLY の 1 beatmap row payload を表す.

    Args:
        request_index (int): filename request の list index. ID request 由来の row は
            `-1` を保持する signed int16 wire 値.
        beatmap_id (int): beatmap identifier を表す signed int32 wire 値.
        beatmapset_id (int): beatmapset identifier を表す signed int32 wire 値.
        thread_id (int): forum thread identifier を表す signed int32 wire 値.
        ranked (int): beatmap info submission status を表す signed int8 wire 値.
        osu_grade (StableGrade): osu mode の strict uint8 stable grade.
        fruits_grade (StableGrade): fruits mode の strict uint8 stable grade.
        taiko_grade (StableGrade): taiko mode の strict uint8 stable grade.
        mania_grade (StableGrade): mania mode の strict uint8 stable grade.
        md5 (str): beatmap checksum を表す BanchoString wire value.

    Attributes:
        request_index (int): filename list index または ID request 用の `-1`.
        beatmap_id (int): signed int32 beatmap identifier.
        beatmapset_id (int): signed int32 beatmapset identifier.
        thread_id (int): signed int32 forum thread identifier.
        ranked (int): signed int8 beatmap info submission status.
        osu_grade (StableGrade): osu mode の stable grade.
        fruits_grade (StableGrade): fruits mode の stable grade.
        taiko_grade (StableGrade): taiko mode の stable grade.
        mania_grade (StableGrade): mania mode の stable grade.
        md5 (str): BanchoString として保持する beatmap checksum.

    Returns:
        BeatmapInfo: 指定した field を wire 順序のまま保持する row instance.

    Raises:
        Caterpillar の pack / unpack 例外: signed primitive の表現可能範囲を超える
            値を pack する場合, payload が途中で欠ける場合, または 0 から 9 以外の
            StableGrade wire 値を strict decode する場合に送出され得る.

    Notes:
        constructor は field 値をそのまま保持し, `request_index` の参照先妥当性を
        検証しない. `-1` は ID request row の semantics を保持する値であり, filename
        row の index は 0 以上であるべきだが, この struct は policy を実装しない.
        `md5` は wire string としてのみ扱い, 32文字 hex validation, metadata lookup,
        packet header, S2C 69 builder はこの struct の責務に含めない.
    """

    request_index: Annotated[int, int16]
    beatmap_id: Annotated[int, int32]
    beatmapset_id: Annotated[int, int32]
    thread_id: Annotated[int, int32]
    ranked: Annotated[int, int8]
    osu_grade: Annotated[StableGrade, Enum(StableGrade, uint8, strict=True)]
    fruits_grade: Annotated[StableGrade, Enum(StableGrade, uint8, strict=True)]
    taiko_grade: Annotated[StableGrade, Enum(StableGrade, uint8, strict=True)]
    mania_grade: Annotated[StableGrade, Enum(StableGrade, uint8, strict=True)]
    md5: Annotated[str, BanchoString]


@cpstruct(order=LittleEndian)
class BeatmapInfoReply:
    """BEATMAP_INFO_REPLY の count-prefixed beatmap row collection を表す.

    Args:
        count (int): `beatmaps` の要素数を示す signed int32. wire contract では
            `len(beatmaps)` と一致しなければならない.
        beatmaps (list[BeatmapInfo]): `count` 件の BeatmapInfo row. 入力順を wire order
            として保持する.

    Attributes:
        count (int): signed int32 row count.
        beatmaps (list[BeatmapInfo]): count に対応する BeatmapInfo row collection.

    Returns:
        BeatmapInfoReply: 指定された count と row 順序を保持する reply instance.

    Raises:
        Caterpillar の pack / unpack 例外: count または row field が wire primitive の
            表現可能範囲を超える場合, count と collection の整合性が pack 時に満たせない
            場合, payload が途中で欠ける場合, または strict StableGrade decode が失敗する
            場合に送出され得る.

    Notes:
        constructor は count を自動計算せず, `count == len(beatmaps)` の invariant を
        検証しない. negative count, trailing bytes, count abuse, malformed payload の
        runtime policy や PacketReadError への変換は後続 parser の責務である. packet
        header, S2C 69 emission, metadata lookup, MD5 validation は追加しない.
    """

    count: Annotated[int, int32]
    beatmaps: Annotated[list[BeatmapInfo], BeatmapInfo[this.count]]


__all__ = ["BeatmapInfo", "BeatmapInfoReply"]

"""BEATMAP_INFO_REPLYのS2C payloadを定義する."""

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
    """BEATMAP_INFO_REPLYの1 beatmap row payloadを表す.

    Attributes:
        request_index (int): filename requestのlist index. ID request由来のrowは-1を保持する.
        beatmap_id (int): signed int32のbeatmap identifier.
        beatmapset_id (int): signed int32のbeatmapset identifier.
        thread_id (int): signed int32のforum thread identifier.
        ranked (int): signed int8のbeatmap info submission status.
        osu_grade (StableGrade): osu modeのstrict uint8 stable grade.
        fruits_grade (StableGrade): fruits modeのstrict uint8 stable grade.
        taiko_grade (StableGrade): taiko modeのstrict uint8 stable grade.
        mania_grade (StableGrade): mania modeのstrict uint8 stable grade.
        md5 (str): BanchoStringで保持するbeatmap checksum.

    Notes:
        このstructはfield値をそのまま保持し, request_indexの参照先妥当性とMD5形式は検証しない.
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
    """BEATMAP_INFO_REPLYのcount-prefixed beatmap row collectionを表す.

    Attributes:
        count (int): beatmapsの要素数を表すsigned int32 wire値.
        beatmaps (list[BeatmapInfo]): count件のBeatmapInfo rowをwire順に保持する一覧.

    Notes:
        このstructはcountを自動計算せず, countとlist長の整合性を検証しない.
    """

    count: Annotated[int, int32]
    beatmaps: Annotated[list[BeatmapInfo], BeatmapInfo[this.count]]


__all__ = ["BeatmapInfo", "BeatmapInfoReply"]

"""BEATMAP_INFOのC2S request payloadを定義する."""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.fields import int32
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.types import BanchoString


@cpstruct(order=LittleEndian)
class BeatmapInfoRequest:
    """BEATMAP_INFOのfilenameとbeatmap ID混在request payloadを表す.

    Attributes:
        filename_count (int): filenamesの要素数を示すsigned int32. wire先頭に配置する.
        filenames (list[str]): filename_count件のBanchoString filenameを入力順に保持する.
        id_count (int): beatmap_idsの要素数を示すsigned int32. filename collectionの直後に置く.
        beatmap_ids (list[int]): id_count件のsigned int32 beatmap IDを入力順に保持する.

    Notes:
        このstructはcountを自動計算せず, countとlist長の整合性も検証しない.
    """

    filename_count: Annotated[int, int32]
    filenames: Annotated[list[str], BanchoString[this.filename_count]]
    id_count: Annotated[int, int32]
    beatmap_ids: Annotated[list[int], int32[this.id_count]]


__all__ = ["BeatmapInfoRequest"]

"""BEATMAP_INFO の C2S request payload 定義。"""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.fields import int32
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.types import BanchoString


@cpstruct(order=LittleEndian)
class BeatmapInfoRequest:
    """BEATMAP_INFO の filename / beatmap ID 混在 request payload を表す。

    Attributes:
        filename_count (int): `filenames` の要素数を示す signed int32。wire 上では
            最初に配置され、`len(filenames)` と一致しなければならない。
        filenames (list[str]): filename request の BanchoString 一覧。直前の
            `filename_count` 件を入力順で保持する。
        id_count (int): `beatmap_ids` の要素数を示す signed int32。filename
            collection の直後に配置され、`len(beatmap_ids)` と一致しなければ
            ならない。
        beatmap_ids (list[int]): beatmap ID の signed int32 一覧。直前の
            `id_count` 件を入力順で保持する。

    Raises:
        Caterpillar の pack / unpack 例外: signed int32 の表現可能範囲を超える
            count または beatmap ID を pack する場合、または必要な field bytes が
            欠けた payload を unpack する場合に送出され得る。

    Notes:
        この struct は count を自動計算せず、負の count、trailing bytes、最大件数、
        request の参照先に対する独自の policy を加えない。これらの packet-level
        policy は後続の C2S parser または runtime workflow の責務である。
    """

    filename_count: Annotated[int, int32]
    filenames: Annotated[list[str], BanchoString[this.filename_count]]
    id_count: Annotated[int, int32]
    beatmap_ids: Annotated[list[int], int32[this.id_count]]


__all__ = ["BeatmapInfoRequest"]

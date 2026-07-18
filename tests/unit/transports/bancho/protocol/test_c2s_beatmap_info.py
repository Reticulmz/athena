"""BeatmapInfo C2S request wire struct のテスト。"""

import struct

from caterpillar.byteorder import LittleEndian
from caterpillar.model import pack, unpack

from osu_server.transports.stable.bancho.protocol.c2s import BeatmapInfoRequest
from osu_server.transports.stable.bancho.protocol.types import BanchoString


def test_beatmap_info_request_round_trips_mixed_collections_in_wire_order() -> None:
    request = BeatmapInfoRequest(
        filename_count=2,
        filenames=["artist - title [normal].osu", "artist - title [hard].osu"],
        id_count=2,
        beatmap_ids=[123, 456],
    )

    payload = pack(request)

    expected_payload = (
        struct.pack("<i", request.filename_count)
        + pack(request.filenames[0], LittleEndian + BanchoString)
        + pack(request.filenames[1], LittleEndian + BanchoString)
        + struct.pack("<i", request.id_count)
        + struct.pack("<ii", *request.beatmap_ids)
    )
    decoded = unpack(BeatmapInfoRequest, payload)

    assert payload == expected_payload
    assert decoded.filename_count == 2
    assert decoded.filenames == ["artist - title [normal].osu", "artist - title [hard].osu"]
    assert decoded.id_count == 2
    assert decoded.beatmap_ids == [123, 456]


def test_beatmap_info_request_round_trips_empty_collections() -> None:
    request = BeatmapInfoRequest(
        filename_count=0,
        filenames=[],
        id_count=0,
        beatmap_ids=[],
    )

    payload = pack(request)
    decoded = unpack(BeatmapInfoRequest, payload)

    assert payload == struct.pack("<ii", 0, 0)
    assert decoded.filename_count == 0
    assert decoded.filenames == []
    assert decoded.id_count == 0
    assert decoded.beatmap_ids == []

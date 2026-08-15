"""Stable osu!direct response formatterの契約を検証するmodule."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.compatibility.stable.direct import STABLE_DIRECT_MORE_RESULTS_SENTINEL
from osu_server.services.queries.beatmaps import (
    DirectPointLookupQueryResult,
    DirectSearchQueryResult,
)
from osu_server.transports.stable.web_legacy.direct import (
    format_direct_point_lookup_response,
    format_direct_search_response,
)

if TYPE_CHECKING:
    from starlette.responses import Response

_UPDATED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_search_response_formats_count_and_stable_rows() -> None:
    """Search結果をcount lineと15 fieldのstable direct rowへ整形する契約を検証する.

    Returns:
        None: count, row field順, difficulty summary順を検証して完了する.
    """
    result = DirectSearchQueryResult(
        beatmapsets=(_beatmapset(10),),
        stable_result_count=1,
    )

    body = _response_text(format_direct_search_response(result))
    lines = body.splitlines()
    fields = lines[1].split("|")

    assert lines[0] == "1"
    assert len(fields) == 15
    assert fields == [
        "10.osz",
        "Artist",
        "Title 10",
        "Mapper",
        "1",
        "10.00",
        "2026-01-02 03:04:05",
        "10",
        "0",
        "0",
        "0",
        "0",
        "0",
        "Easy ★5.00@0,Insane ★6.00@0",
        "0",
    ]


def test_point_lookup_formats_one_row_or_empty_body() -> None:
    """Point lookup結果を単一rowまたは空bodyへ整形する契約を検証する.

    Returns:
        None: 解決済みsetと未解決setのresponse bodyを検証して完了する.
    """
    found = format_direct_point_lookup_response(
        DirectPointLookupQueryResult(beatmapset=_beatmapset(20))
    )
    missing = format_direct_point_lookup_response(DirectPointLookupQueryResult(beatmapset=None))

    assert len(_response_text(found).split("|")) == 15
    assert _response_text(missing) == ""


def test_formatter_prefers_set_level_last_update() -> None:
    """Set-level更新日時がある場合にstable direct rowのLastUpdateへ優先出力する契約を検証する.

    Returns:
        None: child更新日時ではなくBeatmapSetのofficial_last_updated_atをassertして完了する.
    """
    set_updated_at = datetime(2026, 1, 3, 4, 5, 6, tzinfo=UTC)
    response = format_direct_point_lookup_response(
        DirectPointLookupQueryResult(
            beatmapset=_beatmapset(25, official_last_updated_at=set_updated_at)
        )
    )

    fields = _response_text(response).split("|")

    assert fields[6] == "2026-01-03 04:05:06"


def test_formatter_sanitizes_delimiters_and_recounts_omitted_rows() -> None:
    """Formatterがdelimiterを除去し, unsafe rowをstable bodyから除外する契約を検証する.

    Returns:
        None: pipe/newline/source診断の非公開とchildless set除外を検証して完了する.
    """
    result = DirectSearchQueryResult(
        beatmapsets=(
            _beatmapset(
                30,
                artist="A|B\nC",
                title="T\rD",
                creator="M|N",
                versions=("Easy|One@Bad,Extra",),
            ),
            _beatmapset(40, beatmaps=()),
        ),
        stable_result_count=2,
    )

    body = _response_text(format_direct_search_response(result))
    lines = body.splitlines()
    row = lines[1]
    fields = row.split("|")

    assert lines[0] == "1"
    assert len(lines) == 2
    assert len(fields) == 15
    assert "A|B" not in row
    assert "T\rD" not in row
    assert "M|N" not in row
    assert "\n" not in row
    assert "official" not in row
    assert "verified" not in row
    assert "fresh" not in row
    assert fields[13] == "Easy One Bad Extra ★6.00@0"
    assert fields[14] == "0"


def test_direct_status_values_follow_stable_ranked_status_mapping() -> None:
    """Direct rowのstatus fieldがosu!direct row status値に揃う契約を検証する.

    Returns:
        None: getscoresとは異なるdirect row status値を検証して完了する.
    """
    statuses = (
        (BeatmapRankStatus.PENDING, "0"),
        (BeatmapRankStatus.WIP, "0"),
        (BeatmapRankStatus.GRAVEYARD, "-2"),
        (BeatmapRankStatus.RANKED, "1"),
        (BeatmapRankStatus.APPROVED, "2"),
        (BeatmapRankStatus.QUALIFIED, "3"),
        (BeatmapRankStatus.LOVED, "4"),
    )

    for status, expected in statuses:
        body = _response_text(
            format_direct_point_lookup_response(
                DirectPointLookupQueryResult(beatmapset=_beatmapset(50, status=status))
            )
        )
        assert body.split("|")[4] == expected


def test_search_response_preserves_more_sentinel_for_short_upstream_page() -> None:
    """50行のupstream pageでもmore sentinelをcount lineへ出す契約を検証する.

    Returns:
        None: Hinamizawa aeris互換の`101` count lineと短い本文pageを検証して完了する.
    """
    result = DirectSearchQueryResult(
        beatmapsets=tuple(_beatmapset(beatmapset_id) for beatmapset_id in range(1, 51)),
        stable_result_count=STABLE_DIRECT_MORE_RESULTS_SENTINEL,
    )

    lines = _response_text(format_direct_search_response(result)).splitlines()

    assert lines[0] == "101"
    assert len(lines[1:]) == 50


def _response_text(response: Response) -> str:
    """Starlette response bodyをUTF-8 textとして返す.

    Args:
        response (Response): formatterが返したresponse.

    Returns:
        str: response body bytesをUTF-8 decodeした文字列.
    """
    return bytes(response.body).decode()


def _beatmapset(
    beatmapset_id: int,
    *,
    artist: str = "Artist",
    title: str | None = None,
    creator: str = "Mapper",
    status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    versions: tuple[str, ...] = ("Insane", "Easy"),
    beatmaps: tuple[Beatmap, ...] | None = None,
    official_last_updated_at: datetime | None = None,
) -> BeatmapSet:
    """Direct formatter test用のbeatmapset metadataを作る.

    Args:
        beatmapset_id (int): 作成するbeatmapset ID.
        artist (str): rowへ出力するartist.
        title (str | None): rowへ出力するtitle. NoneならID付きtitleを使う.
        creator (str): rowへ出力するcreator.
        status (BeatmapRankStatus): setとchildに設定するrank status.
        versions (tuple[str, ...]): child difficulty名.
        beatmaps (tuple[Beatmap, ...] | None): 明示するchild列. Noneならversionsから作る.
        official_last_updated_at (datetime | None): set-level更新日時. Noneならchildの値を使う.

    Returns:
        BeatmapSet: stable direct formatterへ渡すmetadata.
    """
    return BeatmapSet(
        id=beatmapset_id,
        artist=artist,
        title=title or f"Title {beatmapset_id}",
        creator=creator,
        artist_unicode=None,
        title_unicode=None,
        official_status=status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(
            _beatmaps_for(beatmapset_id, status, versions) if beatmaps is None else beatmaps
        ),
        last_fetched_at=_UPDATED_AT,
        next_refresh_at=None,
        official_last_updated_at=official_last_updated_at,
    )


def _beatmaps_for(
    beatmapset_id: int,
    status: BeatmapRankStatus,
    versions: tuple[str, ...],
) -> tuple[Beatmap, ...]:
    """指定version列からdifficulty順を検証できるchild beatmap列を作る.

    Args:
        beatmapset_id (int): 所属beatmapset ID.
        status (BeatmapRankStatus): childに設定するrank status.
        versions (tuple[str, ...]): difficulty名. 最初の要素は高難度として作る.

    Returns:
        tuple[Beatmap, ...]: difficulty_ratingでsort可能なchild beatmap列.
    """
    return tuple(
        Beatmap(
            id=beatmapset_id * 10 + index,
            beatmapset_id=beatmapset_id,
            checksum_md5=f"{beatmapset_id * 10 + index:032x}",
            mode=BeatmapMode.OSU,
            version=version,
            total_length=120,
            hit_length=100,
            max_combo=500,
            bpm=180.0,
            cs=4.0,
            od=8.0,
            ar=9.0,
            hp=6.0,
            difficulty_rating=6.0 - index,
            official_status=status,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            local_status_override=None,
            metadata_fetch_state=BeatmapFetchState.FRESH,
            file_state=BeatmapFileState.MISSING,
            file_attachment=None,
            last_fetched_at=_UPDATED_AT,
            next_refresh_at=None,
            official_last_updated_at=_UPDATED_AT,
        )
        for index, version in enumerate(versions)
    )

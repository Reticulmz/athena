"""Stable legacy osu!direct response formatterを提供するmodule."""

from __future__ import annotations

from datetime import UTC
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from starlette.responses import Response

from osu_server.domain.beatmaps import (
    BeatmapMode,
    BeatmapRankStatus,
    is_direct_searchable_beatmapset,
)
from osu_server.domain.compatibility.stable.direct import (
    STABLE_DIRECT_MORE_RESULTS_SENTINEL,
    STABLE_DIRECT_PAGE_SIZE,
)
from osu_server.domain.compatibility.stable.mode import StableMode

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.services.queries.beatmaps import (
        DirectPointLookupQueryResult,
        DirectSearchQueryResult,
    )

_TEXT_PLAIN_UTF8 = "text/plain; charset=utf-8"
_DIRECT_STATUS_TO_WIRE: Final[dict[BeatmapRankStatus, int | None]] = {
    BeatmapRankStatus.NOT_SUBMITTED: None,
    BeatmapRankStatus.UNKNOWN: None,
    BeatmapRankStatus.PENDING: 0,
    BeatmapRankStatus.WIP: 0,
    BeatmapRankStatus.GRAVEYARD: 0,
    BeatmapRankStatus.RANKED: 2,
    BeatmapRankStatus.APPROVED: 3,
    BeatmapRankStatus.QUALIFIED: 4,
    BeatmapRankStatus.LOVED: 5,
}
_MODE_TO_WIRE: Final[dict[BeatmapMode, int]] = {
    BeatmapMode.OSU: StableMode.Osu.value,
    BeatmapMode.TAIKO: StableMode.Taiko.value,
    BeatmapMode.FRUITS: StableMode.Fruits.value,
    BeatmapMode.MANIA: StableMode.Mania.value,
}


def format_direct_search_response(result: DirectSearchQueryResult) -> Response:
    """Direct search query resultをstable direct search bodyへ整形する.

    Args:
        result (DirectSearchQueryResult): metadata hydration済みの検索結果.

    Returns:
        Response: count lineとstable direct rowを持つtext/plain response.
    """
    rows = tuple(
        row
        for beatmapset in result.beatmapsets
        if (row := _format_beatmapset_row(beatmapset)) is not None
    )
    count = (
        STABLE_DIRECT_MORE_RESULTS_SENTINEL
        if result.stable_result_count == STABLE_DIRECT_MORE_RESULTS_SENTINEL
        and len(rows) == STABLE_DIRECT_PAGE_SIZE
        else len(rows)
    )
    body = "\n".join((str(count), *rows)).encode()
    return _text_response(body)


def format_direct_point_lookup_response(result: DirectPointLookupQueryResult) -> Response:
    """Direct point lookup resultをstable direct pickup bodyへ整形する.

    Args:
        result (DirectPointLookupQueryResult): point lookupで得たbeatmapset結果.

    Returns:
        Response: 解決済みなら単一stable direct row, 未解決なら空body.
    """
    if result.beatmapset is None:
        return _text_response(b"")
    row = _format_beatmapset_row(result.beatmapset)
    return _text_response(row.encode() if row is not None else b"")


def _format_beatmapset_row(beatmapset: BeatmapSet) -> str | None:
    """Beatmapset metadataをstable directの15 field rowへ変換する.

    Args:
        beatmapset (BeatmapSet): stable direct bodyへ出力するmetadata.

    Returns:
        str | None: 変換可能なpipe-delimited row. 安全に表現できない場合はNone.
    """
    if not is_direct_searchable_beatmapset(beatmapset):
        return None
    status = _DIRECT_STATUS_TO_WIRE.get(beatmapset.official_status)
    if status is None:
        return None
    difficulty_summaries = _format_difficulty_summaries(beatmapset.beatmaps)
    if not difficulty_summaries:
        return None

    artist = _sanitize(beatmapset.artist)
    title = _sanitize(beatmapset.title)
    creator = _sanitize(beatmapset.creator)
    fields = (
        f"{beatmapset.id} {artist} - {title}.osz",
        artist,
        title,
        creator,
        str(status),
        "0.0",
        _last_update_text(beatmapset.beatmaps),
        str(beatmapset.id),
        "0",
        "0",
        "0",
        "0",
        "0",
        difficulty_summaries,
        "0",
    )
    return "|".join(fields)


def _format_difficulty_summaries(beatmaps: tuple[Beatmap, ...]) -> str:
    """Child beatmap列を`version@mode`のstable direct summaryへ変換する.

    Args:
        beatmaps (tuple[Beatmap, ...]): beatmapsetに属するchild beatmap列.

    Returns:
        str: difficulty_rating順のsummary. 対応modeがないchildは除外する.
    """
    summaries: list[str] = []
    for beatmap in sorted(beatmaps, key=_difficulty_sort_key):
        mode = _MODE_TO_WIRE.get(beatmap.mode)
        if mode is not None:
            summaries.append(f"{_sanitize(beatmap.version)}@{mode}")
    return ",".join(summaries)


def _difficulty_sort_key(beatmap: Beatmap) -> tuple[float, int]:
    """Stable direct rowのchild表示順を決めるsort keyを返す.

    Args:
        beatmap (Beatmap): 並び替えるchild beatmap.

    Returns:
        tuple[float, int]: difficulty ratingを優先し, 同値ではbeatmap IDで安定化したkey.
    """
    rating = beatmap.difficulty_rating if beatmap.difficulty_rating is not None else 0.0
    return (rating, beatmap.id)


def _last_update_text(beatmaps: tuple[Beatmap, ...]) -> str:
    """Child metadataからstable direct row用の最終更新時刻を返す.

    Args:
        beatmaps (tuple[Beatmap, ...]): last updateを抽出するchild beatmap列.

    Returns:
        str: UTCの`YYYY-MM-DD HH:MM:SS`表記. 不明な場合は空文字列.
    """
    values = tuple(
        beatmap.official_last_updated_at
        for beatmap in beatmaps
        if beatmap.official_last_updated_at is not None
    )
    if not values:
        return ""
    return _utc_text(max(values))


def _utc_text(value: datetime) -> str:
    """Datetimeをstable direct row向けのUTC時刻文字列へ変換する.

    Args:
        value (datetime): 変換する日時.

    Returns:
        str: timezone suffixを持たないUTC日時文字列.
    """
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _sanitize(text: str) -> str:
    """Stable direct field delimiterを空白へ置換する.

    Args:
        text (str): upstream metadata由来のfield文字列.

    Returns:
        str: pipe, 改行, child summary separatorを含まない文字列.
    """
    return (
        text.replace("|", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("@", " ")
        .replace(",", " ")
    )


def _text_response(content: bytes) -> Response:
    """Stable direct text/plain responseを作る.

    Args:
        content (bytes): response body bytes.

    Returns:
        Response: HTTP 200のtext/plain response.
    """
    return Response(
        content=content,
        status_code=HTTPStatus.OK,
        media_type=_TEXT_PLAIN_UTF8,
    )


__all__ = [
    "format_direct_point_lookup_response",
    "format_direct_search_response",
]

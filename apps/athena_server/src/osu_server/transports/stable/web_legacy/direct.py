"""Stable legacy osu!direct response formatterを提供するmodule."""

from __future__ import annotations

from datetime import UTC
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import structlog
from starlette.responses import Response

from osu_server.domain.beatmaps import (
    BeatmapMode,
    BeatmapRankStatus,
    DirectAccessDecision,
    DirectCoverageRecord,
    is_direct_searchable_beatmapset,
)
from osu_server.domain.compatibility.stable.direct import (
    STABLE_DIRECT_MORE_RESULTS_SENTINEL,
)
from osu_server.domain.compatibility.stable.mode import StableMode

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from starlette.requests import Request

    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.services.queries.beatmaps import (
        DirectPointLookupQuery,
        DirectPointLookupQueryResult,
        DirectSearchQuery,
        DirectSearchQueryResult,
    )
    from osu_server.transports.stable.web_legacy.direct_access import StableDirectAccessGate
    from osu_server.transports.stable.web_legacy.mappers import (
        StableDirectPointLookupQueryParser,
        StableDirectSearchQueryParser,
    )

_TEXT_PLAIN_UTF8 = "text/plain; charset=utf-8"
_DIRECT_STATUS_TO_WIRE: Final[dict[BeatmapRankStatus, int | None]] = {
    BeatmapRankStatus.NOT_SUBMITTED: None,
    BeatmapRankStatus.UNKNOWN: None,
    BeatmapRankStatus.PENDING: 0,
    BeatmapRankStatus.WIP: 0,
    BeatmapRankStatus.GRAVEYARD: -2,
    BeatmapRankStatus.RANKED: 1,
    BeatmapRankStatus.APPROVED: 2,
    BeatmapRankStatus.QUALIFIED: 3,
    BeatmapRankStatus.LOVED: 4,
}
_MODE_TO_WIRE: Final[dict[BeatmapMode, int]] = {
    BeatmapMode.OSU: StableMode.Osu.value,
    BeatmapMode.TAIKO: StableMode.Taiko.value,
    BeatmapMode.FRUITS: StableMode.Fruits.value,
    BeatmapMode.MANIA: StableMode.Mania.value,
}

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class StableDirectSearchCoverageRecorder(Protocol):
    """Stable direct searchが観測したcoverageを保存するcommand境界を表す."""

    async def execute(self, record: DirectCoverageRecord) -> None:
        """Coverage recordを保存する.

        Args:
            record (DirectCoverageRecord): query use-caseが返したcoverage record.

        Returns:
            None: coverage保存を完了する.
        """
        ...


class StableDirectSearchHandler:
    """`GET /web/osu-search.php`を認証済みdirect search responseへ変換する.

    Attributes:
        _access_gate (StableDirectAccessGate): legacy credentialとdirect access policyを判定する
            gate.
        _search_parser (StableDirectSearchQueryParser): query parameterをsearch requestへ変換する
            parser.
        _search_query (DirectSearchQuery): catalog候補をmetadataへhydrateするquery use-case.
        _coverage_recorder (StableDirectSearchCoverageRecorder): upstream検索coverage保存command.
    """

    _access_gate: StableDirectAccessGate
    _search_parser: StableDirectSearchQueryParser
    _search_query: DirectSearchQuery
    _coverage_recorder: StableDirectSearchCoverageRecorder

    def __init__(
        self,
        *,
        access_gate: StableDirectAccessGate,
        search_parser: StableDirectSearchQueryParser,
        search_query: DirectSearchQuery,
        coverage_recorder: StableDirectSearchCoverageRecorder,
    ) -> None:
        """Direct search handlerの依存を保持する.

        Args:
            access_gate (StableDirectAccessGate): direct work前の認証とaccess policy.
            search_parser (StableDirectSearchQueryParser): stable search query parser.
            search_query (DirectSearchQuery): direct search query use-case.
            coverage_recorder (StableDirectSearchCoverageRecorder):
                upstream検索coverage保存command.
        """
        self._access_gate = access_gate
        self._search_parser = search_parser
        self._search_query = search_query
        self._coverage_recorder = coverage_recorder

    async def __call__(self, request: Request) -> Response:
        """Starlette requestのquery parameterをstable direct search responseへ変換する.

        Args:
            request (Request): stable clientから届いたGET request.

        Returns:
            Response: 認証とdirect search結果を反映したstable response.
        """
        return await self.respond(request.query_params)

    async def respond(self, query: Mapping[str, str]) -> Response:
        """Stable direct search queryを認証してwire responseへ変換する.

        Args:
            query (Mapping[str, str]): stable clientが送るquery parameter mapping.

        Returns:
            Response: 認証またはaccess拒否には空のHTTP 401, malformed queryには空検索,
                成功時にはstable direct count lineとrowを返す.
        """
        access_result = await self._access_gate.authorize(query)
        if access_result.decision is not DirectAccessDecision.ALLOWED:
            return _access_failure_response()

        user_id = access_result.authenticated_user_id
        if user_id is None:
            return _access_failure_response()

        parse_result = self._search_parser.parse(query, authenticated_user_id=user_id)
        if parse_result.request is None:
            return _text_response(b"0")

        result = await self._search_query.execute(parse_result.request)
        await self._record_coverage(result)
        return format_direct_search_response(result)

    async def _record_coverage(self, result: DirectSearchQueryResult) -> None:
        """検索結果が持つcoverage recordをbest-effortで保存する.

        Args:
            result (DirectSearchQueryResult): direct search query use-caseの結果.

        Returns:
            None: coverageがないか保存完了または失敗log後に返る.
        """
        if result.coverage_record is None:
            return
        try:
            await self._coverage_recorder.execute(result.coverage_record)
        except Exception as exc:
            logger.warning(
                "osu_direct_search_coverage_record_failed",
                exception_type=type(exc).__name__,
            )


class StableDirectPointLookupHandler:
    """`GET /web/osu-search-set.php`を認証済みpoint lookup responseへ変換する.

    Attributes:
        _access_gate (StableDirectAccessGate): legacy credentialとdirect access policyを判定する
            gate.
        _point_lookup_parser (StableDirectPointLookupQueryParser):
            query parameterをlookup requestへ変換するparser.
        _point_lookup_query (DirectPointLookupQuery): metadata point lookup query use-case.
    """

    _access_gate: StableDirectAccessGate
    _point_lookup_parser: StableDirectPointLookupQueryParser
    _point_lookup_query: DirectPointLookupQuery

    def __init__(
        self,
        *,
        access_gate: StableDirectAccessGate,
        point_lookup_parser: StableDirectPointLookupQueryParser,
        point_lookup_query: DirectPointLookupQuery,
    ) -> None:
        """Direct point lookup handlerの依存を保持する.

        Args:
            access_gate (StableDirectAccessGate): direct work前の認証とaccess policy.
            point_lookup_parser (StableDirectPointLookupQueryParser): stable point lookup parser.
            point_lookup_query (DirectPointLookupQuery): direct point lookup query use-case.
        """
        self._access_gate = access_gate
        self._point_lookup_parser = point_lookup_parser
        self._point_lookup_query = point_lookup_query

    async def __call__(self, request: Request) -> Response:
        """Starlette requestのquery parameterをstable point lookup responseへ変換する.

        Args:
            request (Request): stable clientから届いたGET request.

        Returns:
            Response: 認証とpoint lookup結果を反映したstable response.
        """
        return await self.respond(request.query_params)

    async def respond(self, query: Mapping[str, str]) -> Response:
        """Stable direct point lookup queryを認証してwire responseへ変換する.

        Args:
            query (Mapping[str, str]): stable clientが送るquery parameter mapping.

        Returns:
            Response: 認証またはaccess拒否には空のHTTP 401, malformedまたは未解決lookupには
                空のHTTP 200, 成功時にはstable direct rowを返す.
        """
        access_result = await self._access_gate.authorize(query)
        if access_result.decision is not DirectAccessDecision.ALLOWED:
            return _access_failure_response()

        user_id = access_result.authenticated_user_id
        if user_id is None:
            return _access_failure_response()

        parse_result = self._point_lookup_parser.parse(query, authenticated_user_id=user_id)
        if parse_result.request is None:
            return _text_response(b"")

        result = await self._point_lookup_query.execute(parse_result.request)
        return format_direct_point_lookup_response(result)


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
        f"{beatmapset.id}.osz",
        artist,
        title,
        creator,
        str(status),
        "10.00",
        _last_update_text(beatmapset),
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
    """Child beatmap列を`version ★stars@mode`のstable direct summaryへ変換する.

    Args:
        beatmaps (tuple[Beatmap, ...]): beatmapsetに属するchild beatmap列.

    Returns:
        str: mode, difficulty_rating順のsummary. 対応modeがないchildは除外する.
    """
    summaries: list[str] = []
    for beatmap in sorted(beatmaps, key=_difficulty_sort_key):
        mode = _MODE_TO_WIRE.get(beatmap.mode)
        if mode is not None:
            summaries.append(
                f"{_sanitize(beatmap.version)} ★{_difficulty_rating_text(beatmap)}@{mode}"
            )
    return ",".join(summaries)


def _difficulty_sort_key(beatmap: Beatmap) -> tuple[int, float, int]:
    """Stable direct rowのchild表示順を決めるsort keyを返す.

    Args:
        beatmap (Beatmap): 並び替えるchild beatmap.

    Returns:
        tuple[int, float, int]: mode, difficulty ratingを優先し, 同値ではbeatmap IDで安定化したkey.
    """
    mode = _MODE_TO_WIRE.get(beatmap.mode, 999)
    rating = beatmap.difficulty_rating if beatmap.difficulty_rating is not None else 0.0
    return (mode, rating, beatmap.id)


def _difficulty_rating_text(beatmap: Beatmap) -> str:
    """Child beatmapの星数をstable direct表示文字列へ変換する.

    Args:
        beatmap (Beatmap): difficulty summaryへ出力するchild beatmap.

    Returns:
        str: 小数2桁のdifficulty rating. 不明な場合は0.00.
    """
    rating = beatmap.difficulty_rating if beatmap.difficulty_rating is not None else 0.0
    return f"{rating:.2f}"


def _last_update_text(beatmapset: BeatmapSet) -> str:
    """Stable direct row用の最終更新時刻をset-level優先で返す.

    Args:
        beatmapset (BeatmapSet): last updateを抽出するbeatmapset metadata.

    Returns:
        str: UTCの`YYYY-MM-DD HH:MM:SS`表記. 不明な場合は空文字列.
    """
    if beatmapset.official_last_updated_at is not None:
        return _utc_text(beatmapset.official_last_updated_at)
    values = tuple(
        beatmap.official_last_updated_at
        for beatmap in beatmapset.beatmaps
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


def _access_failure_response() -> Response:
    """Stable direct auth/access failure responseを作る.

    Returns:
        Response: catalog bodyを持たないHTTP 401 response.
    """
    return Response(content=b"", status_code=HTTPStatus.UNAUTHORIZED)


__all__ = [
    "StableDirectPointLookupHandler",
    "StableDirectSearchHandler",
    "format_direct_point_lookup_response",
    "format_direct_search_response",
]

"""Stable getscores requestを認証, 解決, response整形するendpoint adapterを提供する.

認証失敗には空のHTTP 401を返し, 利用不可, 更新可能, leaderboard headerの各結果には
stable互換のtext responseを返す. credentialや内部provenanceはresponseへ公開しない.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import structlog
from starlette.responses import Response

from osu_server.domain.beatmaps import BeatmapResolveOptions
from osu_server.domain.compatibility.stable.getscores import GetscoresOutcomeKind
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupRequest,
)
from osu_server.services.queries.identity import SessionCredentialsQueryInput

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.requests import Request

    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.domain.compatibility.stable.getscores import (
        GetscoresPersonalBest,
        GetscoresRequest,
    )
    from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
    from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService
    from osu_server.services.queries.identity import SessionCredentialsQuery
    from osu_server.services.queries.scores import BeatmapScoreListingQuery
    from osu_server.transports.stable.web_legacy.mappers import (
        GetscoresQueryParser,
        GetscoresStatusMapper,
    )

_TEXT_PLAIN_UTF8 = "text/plain; charset=utf-8"

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


def _sanitize(text: str) -> str:
    """Getscoresのpipe-delimited fieldから区切り文字と改行を除去する.

    Args:
        text (str): stable response fieldへ入れる未加工文字列.

    Returns:
        str: `|`, CR, LFを空白へ置換した文字列.
    """
    return text.replace("|", " ").replace("\r", " ").replace("\n", " ")


class StableGetscoresExchange:
    """Stable getscoresの認証, metadata warmup, response選択を調整する.

    Attributes:
        _auth_query (SessionCredentialsQuery): legacy credentialを検証するquery.
        _getscores_parser (GetscoresQueryParser): query parameterをdomain requestへ変換するparser.
        _getscores_query (BeatmapScoreListingQuery): leaderboard outcomeを解決するquery.
        _status_mapper (GetscoresStatusMapper): beatmap statusをstable wire valueへ変換するmapper.
        _beatmap_resolver (BeatmapMirrorService): metadata fetchを要求するmirror service.
        _beatmap_file_warmup (RequestBeatmapFileWarmupUseCase): .osu file warmupを要求するuse case.
        _beatmap_metadata_wait_seconds (float): metadata解決を待つ最大秒数.
    """

    def __init__(
        self,
        auth_query: SessionCredentialsQuery,
        getscores_parser: GetscoresQueryParser,
        getscores_query: BeatmapScoreListingQuery,
        status_mapper: GetscoresStatusMapper,
        beatmap_resolver: BeatmapMirrorService,
        beatmap_file_warmup: RequestBeatmapFileWarmupUseCase,
        beatmap_metadata_wait_seconds: float,
    ) -> None:
        """Getscores exchangeのquery, mapper, warmup依存を設定する.

        Args:
            auth_query (SessionCredentialsQuery): legacy session credentialを検証するquery.
            getscores_parser (GetscoresQueryParser): stable queryをgetscores requestへ
                変換するparser.
            getscores_query (BeatmapScoreListingQuery): beatmap leaderboardを取得するquery.
            status_mapper (GetscoresStatusMapper): header用statusをwire valueへ変換するmapper.
            beatmap_resolver (BeatmapMirrorService): response前にmetadataを解決するservice.
            beatmap_file_warmup (RequestBeatmapFileWarmupUseCase): .osu file取得を要求するuse case.
            beatmap_metadata_wait_seconds (float): metadata解決を待機する秒数.
        """
        self._auth_query: SessionCredentialsQuery = auth_query
        self._getscores_parser: GetscoresQueryParser = getscores_parser
        self._getscores_query: BeatmapScoreListingQuery = getscores_query
        self._status_mapper: GetscoresStatusMapper = status_mapper
        self._beatmap_resolver: BeatmapMirrorService = beatmap_resolver
        self._beatmap_file_warmup: RequestBeatmapFileWarmupUseCase = beatmap_file_warmup
        self._beatmap_metadata_wait_seconds: float = beatmap_metadata_wait_seconds

    async def respond(self, query: Mapping[str, str]) -> Response:
        """Stable getscores queryを認証してwire responseへ変換する.

        Args:
            query (Mapping[str, str]): stable clientが送るquery parameter mapping.

        Returns:
            Response: 認証失敗には空のHTTP 401, それ以外にはstable互換のHTTP 200 response.

        Notes:
            metadata解決とfile warmupの失敗は記録するが, response outcomeの選択を変更しない.
        """
        auth_query_result = await self._auth_query.execute(
            SessionCredentialsQueryInput(
                username=query.get("us"),
                password_md5=query.get("ha"),
            ),
        )
        auth_result = auth_query_result.outcome
        if auth_result.failure is not None:
            logger.info(
                "getscores_auth_failed",
                failure_reason=auth_result.failure.value,
            )
            return Response(content=b"", status_code=HTTPStatus.UNAUTHORIZED)

        user_id = auth_result.user_id
        assert user_id is not None

        parse_result = self._getscores_parser.parse(query)
        if parse_result.error is not None or parse_result.request is None:
            error_value = parse_result.error.value if parse_result.error is not None else None
            logger.info(
                "getscores_identity_invalid",
                parse_error=error_value,
                user_id=user_id,
            )
            return format_getscores_unavailable_response()

        request_obj = parse_result.request
        if request_obj.parse_warnings:
            logger.info(
                "getscores_parse_warning",
                warnings=[w.value for w in request_obj.parse_warnings],
                user_id=user_id,
            )
        if request_obj.anti_cheat_signal:
            logger.info(
                "getscores_anti_cheat_signal",
                user_id=user_id,
            )

        await self._prepare_metadata(request_obj, user_id=user_id)
        outcome = await self._getscores_query.resolve(request_obj, user_id=user_id)

        if outcome.kind is GetscoresOutcomeKind.UNAVAILABLE:
            await self._request_beatmap_file_warmup(
                user_id=user_id,
                checksum_md5=request_obj.checksum_md5,
            )
            logger.info(
                "getscores_unavailable",
                resolve_reason=outcome.reason.value,
                user_id=user_id,
            )
            return format_getscores_unavailable_response()

        if outcome.kind is GetscoresOutcomeKind.UPDATE_AVAILABLE:
            assert outcome.header is not None  # invariant for UPDATE_AVAILABLE outcomes
            await self._request_beatmap_file_warmup(
                user_id=user_id,
                beatmap_id=outcome.header.beatmap.id,
            )
            logger.info(
                "getscores_update_available",
                resolve_reason=outcome.reason.value,
                user_id=user_id,
            )
            return format_getscores_update_available_response()

        # HEADER outcome
        assert outcome.header is not None  # invariant for HEADER outcomes
        await self._request_beatmap_file_warmup(
            user_id=user_id,
            beatmap_id=outcome.header.beatmap.id,
        )
        wire_status = self._status_mapper.map_header_status(outcome.header.beatmap)
        if wire_status is None:
            logger.info(
                "getscores_unavailable",
                resolve_reason=outcome.reason.value,
                user_id=user_id,
            )
            return format_getscores_unavailable_response()

        return format_getscores_header_response(
            status=wire_status,
            beatmap=outcome.header.beatmap,
            beatmapset=outcome.header.beatmapset,
            personal_best=outcome.header.personal_best,
            score_rows=outcome.header.score_rows,
        )

    async def _prepare_metadata(
        self,
        request: GetscoresRequest,
        *,
        user_id: int | None,
    ) -> None:
        """Stable responseを解決する前に必要なbeatmap metadataを要求する.

        Args:
            request (GetscoresRequest): metadata検索に使うchecksumまたはbeatmapset hintを持つ
                request.
            user_id (int | None): diagnosticsに記録する認証済みuser ID.

        Returns:
            None: metadata requestを試行し, responseを返さずに完了する.

        Notes:
            resolverの例外は記録して抑制し, stable response選択を妨げない.
        """
        try:
            if request.beatmapset_id_hint is not None:
                result = await self._beatmap_resolver.resolve_by_beatmapset_id(
                    request.beatmapset_id_hint,
                    BeatmapResolveOptions(
                        wait_timeout_seconds=self._beatmap_metadata_wait_seconds,
                    ),
                )
                logger.info(
                    "getscores_metadata_resolved",
                    user_id=user_id,
                    beatmapset_id=request.beatmapset_id_hint,
                    metadata_status=result.metadata_status.value,
                    reason=result.reason,
                )
                if result.beatmapset is not None or request.checksum_md5 is None:
                    return

            if request.checksum_md5 is not None:
                result = await self._beatmap_resolver.resolve_by_checksum(
                    request.checksum_md5,
                    BeatmapResolveOptions(
                        wait_timeout_seconds=self._beatmap_metadata_wait_seconds,
                    ),
                )
                logger.info(
                    "getscores_metadata_resolved",
                    user_id=user_id,
                    beatmap_id=result.beatmap.id if result.beatmap is not None else None,
                    metadata_status=result.metadata_status.value,
                    file_status=result.file_status.value,
                    reason=result.reason,
                )
                if result.beatmap is not None:
                    return
        except Exception:
            logger.exception(
                "getscores_metadata_resolve_failed",
                user_id=user_id,
                beatmapset_id=request.beatmapset_id_hint,
                has_checksum=request.checksum_md5 is not None,
            )

    async def _request_beatmap_file_warmup(
        self,
        *,
        user_id: int,
        beatmap_id: int | None = None,
        checksum_md5: str | None = None,
    ) -> None:
        """Response選択を変えずに対象.osu fileのwarmupを要求する.

        Args:
            user_id (int): warmup要求を行う認証済みuser ID.
            beatmap_id (int | None): warmup対象beatmap ID. checksum_md5と両方がない場合は
                何もしない.
            checksum_md5 (str | None): warmup対象beatmapのMD5 checksum.

        Returns:
            None: warmupを要求するか, 対象がなければ何もせず完了する.

        Notes:
            warmup失敗は記録して抑制し, 既に選択したstable responseを変えない.
        """
        if beatmap_id is None and checksum_md5 is None:
            return

        try:
            _ = await self._beatmap_file_warmup.execute(
                BeatmapFileWarmupRequest(
                    entrance=BeatmapFileWarmupEntrance.STABLE_GETSCORES,
                    user_id=user_id,
                    beatmap_id=beatmap_id,
                    checksum_md5=checksum_md5,
                )
            )
        except Exception:
            logger.exception(
                "getscores_beatmap_file_warmup_failed",
                user_id=user_id,
                beatmap_id=beatmap_id,
                has_checksum=checksum_md5 is not None,
            )


class GetscoresHandler:
    """`GET /web/osu-osz2-getscores.php`をexchangeへ委譲するStarlette adapter.

    Attributes:
        _exchange (StableGetscoresExchange): request queryをstable responseへ変換するexchange.
    """

    def __init__(
        self,
        auth_query: SessionCredentialsQuery,
        getscores_parser: GetscoresQueryParser,
        getscores_query: BeatmapScoreListingQuery,
        status_mapper: GetscoresStatusMapper,
        beatmap_resolver: BeatmapMirrorService,
        beatmap_file_warmup: RequestBeatmapFileWarmupUseCase,
        beatmap_metadata_wait_seconds: float,
    ) -> None:
        """Getscores requestを処理するexchangeを構成する.

        Args:
            auth_query (SessionCredentialsQuery): legacy session credentialを検証するquery.
            getscores_parser (GetscoresQueryParser): stable queryをgetscores requestへ
                変換するparser.
            getscores_query (BeatmapScoreListingQuery): beatmap leaderboardを取得するquery.
            status_mapper (GetscoresStatusMapper): header用statusをwire valueへ変換するmapper.
            beatmap_resolver (BeatmapMirrorService): response前にmetadataを解決するservice.
            beatmap_file_warmup (RequestBeatmapFileWarmupUseCase): .osu file取得を要求するuse case.
            beatmap_metadata_wait_seconds (float): metadata解決を待機する秒数.
        """
        self._exchange: StableGetscoresExchange = StableGetscoresExchange(
            auth_query=auth_query,
            getscores_parser=getscores_parser,
            getscores_query=getscores_query,
            status_mapper=status_mapper,
            beatmap_resolver=beatmap_resolver,
            beatmap_file_warmup=beatmap_file_warmup,
            beatmap_metadata_wait_seconds=beatmap_metadata_wait_seconds,
        )

    async def __call__(self, request: Request) -> Response:
        """Starlette requestのquery parameterをstable getscores responseへ変換する.

        Args:
            request (Request): stable clientから届いたGET request.

        Returns:
            Response: 認証とleaderboard解決結果を反映したstable response.
        """
        return await self._exchange.respond(request.query_params)


def format_getscores_unavailable_response() -> Response:
    """Stable getscoresの利用不可wire responseを構築する.

    Returns:
        Response: `-1|false`をbodyに持つtext/plainのHTTP 200 response.
    """
    return Response(
        content=b"-1|false",
        status_code=HTTPStatus.OK,
        media_type=_TEXT_PLAIN_UTF8,
    )


def format_getscores_update_available_response() -> Response:
    """Stable getscoresの更新可能wire responseを構築する.

    Returns:
        Response: `1|false`をbodyに持つtext/plainのHTTP 200 response.
    """
    return Response(
        content=b"1|false",
        status_code=HTTPStatus.OK,
        media_type=_TEXT_PLAIN_UTF8,
    )


def format_getscores_header_response(
    *,
    status: int,
    beatmap: Beatmap,
    beatmapset: BeatmapSet,
    personal_best: GetscoresPersonalBest | None = None,
    score_rows: tuple[GetscoresPersonalBest, ...] = (),
) -> Response:
    """Stable getscoresのleaderboard headerとscore rowのresponseを構築する.

    Args:
        status (int): stable wire protocolのbeatmap status値.
        beatmap (Beatmap): response headerへ入れるbeatmap.
        beatmapset (BeatmapSet): artistとtitleを提供するbeatmapset.
        personal_best (GetscoresPersonalBest | None): viewerのpersonal best. 不在時は空rowにする.
        score_rows (tuple[GetscoresPersonalBest, ...]): leaderboard順のscore row群.

    Returns:
        Response: pipe-delimited headerとscore rowを持つtext/plainのHTTP 200 response.
    """
    artist = _sanitize(beatmapset.artist)
    title = _sanitize(beatmapset.title)
    personal_best_row = _format_score_row(personal_best) if personal_best is not None else ""
    score_count = len(score_rows)
    formatted_score_rows = "\n".join(_format_score_row(row) for row in score_rows)

    body = (
        f"{status}|false|{beatmap.id}|{beatmap.beatmapset_id}|{score_count}||\n"
        f"0\n"
        f"[bold:0,size:20]{artist}|{title}\n"
        f"0\n"
        f"{personal_best_row}\n"
        f"{formatted_score_rows}\n"
    ).encode()
    return Response(
        content=body,
        status_code=HTTPStatus.OK,
        media_type=_TEXT_PLAIN_UTF8,
    )


def _format_score_row(row: GetscoresPersonalBest) -> str:
    """Getscoresのpersonal best値を固定field順のwire rowへ整形する.

    Args:
        row (GetscoresPersonalBest): stable responseへ出力するscore row.

    Returns:
        str: pipe-delimitedの16 field score row.
    """
    submitted_at_seconds = int(row.submitted_at.timestamp())
    return "|".join(
        (
            str(row.score_id),
            _sanitize(row.username),
            str(row.score),
            str(row.max_combo),
            str(row.n50),
            str(row.n100),
            str(row.n300),
            str(row.miss),
            str(row.katu),
            str(row.geki),
            "1" if row.perfect else "0",
            str(row.mods),
            str(row.user_id),
            str(row.rank),
            str(submitted_at_seconds),
            "1" if row.has_replay else "0",
        )
    )

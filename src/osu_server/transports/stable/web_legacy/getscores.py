"""GetscoresHandler — GET /web/osu-osz2-getscores.php handler for stable client.

Pipeline: authenticate (us/ha + active session) -> parse query -> resolve
metadata -> format response body.  Returns 401 with empty body for auth
failures, and stable 200 text/plain bodies for unavailable / update-available
/ known-header outcomes.  Never exposes provenance fields in the response.

Operator-observable diagnostics are emitted via structlog at each branch
without leaking ``ha`` (password md5), raw ``us`` values, or any internal
provenance into stable response bodies.
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
    return text.replace("|", " ").replace("\r", " ").replace("\n", " ")


class StableGetscoresExchange:
    """Stable getscores exchange: auth, parse, warmup, and response selection."""

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
        self._auth_query: SessionCredentialsQuery = auth_query
        self._getscores_parser: GetscoresQueryParser = getscores_parser
        self._getscores_query: BeatmapScoreListingQuery = getscores_query
        self._status_mapper: GetscoresStatusMapper = status_mapper
        self._beatmap_resolver: BeatmapMirrorService = beatmap_resolver
        self._beatmap_file_warmup: RequestBeatmapFileWarmupUseCase = beatmap_file_warmup
        self._beatmap_metadata_wait_seconds: float = beatmap_metadata_wait_seconds

    async def respond(self, query: Mapping[str, str]) -> Response:
        """Resolve one stable getscores query into its wire response."""
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
        """Request metadata fetch before resolving the stable response."""
        try:
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
                return

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
        """Request .osu warmup without affecting getscores response selection."""
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
    """Starlette adapter for ``GET /web/osu-osz2-getscores.php``."""

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
        """Delegate stable getscores semantics to the exchange module."""
        return await self._exchange.respond(request.query_params)


def format_getscores_unavailable_response() -> Response:
    return Response(
        content=b"-1|false",
        status_code=HTTPStatus.OK,
        media_type=_TEXT_PLAIN_UTF8,
    )


def format_getscores_update_available_response() -> Response:
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

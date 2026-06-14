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

from osu_server.domain.legacy_getscores import GetscoresOutcomeKind
from osu_server.services.queries.identity import LegacyWebAuthQueryInput

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.services.legacy_getscores_service import (
        GetscoresQueryParser,
        GetscoresStatusMapper,
    )
    from osu_server.services.queries.identity import LegacyWebAuthQuery
    from osu_server.services.queries.scores import LegacyGetscoresQuery

_TEXT_PLAIN_UTF8 = "text/plain; charset=utf-8"

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


def _sanitize(text: str) -> str:
    return text.replace("|", " ").replace("\r", " ").replace("\n", " ")


class GetscoresHandler:
    """Starlette handler for ``GET /web/osu-osz2-getscores.php``.

    Receives DI dependencies in ``__init__`` and acts as a callable ASGI
    endpoint via ``__call__``.
    """

    def __init__(
        self,
        auth_query: LegacyWebAuthQuery,
        getscores_parser: GetscoresQueryParser,
        getscores_query: LegacyGetscoresQuery,
        status_mapper: GetscoresStatusMapper,
    ) -> None:
        self._auth_query: LegacyWebAuthQuery = auth_query
        self._getscores_parser: GetscoresQueryParser = getscores_parser
        self._getscores_query: LegacyGetscoresQuery = getscores_query
        self._status_mapper: GetscoresStatusMapper = status_mapper

    async def __call__(self, request: Request) -> Response:
        """Handle a getscores request, returning the stable wire body."""
        username = request.query_params.get("us")
        password_md5 = request.query_params.get("ha")

        auth_query_result = await self._auth_query.execute(
            LegacyWebAuthQueryInput(
                username=username,
                password_md5=password_md5,
            ),
        )
        auth_result = auth_query_result.outcome
        if auth_result.failure is not None:
            logger.info(
                "getscores_auth_failed",
                failure_reason=auth_result.failure.value,
            )
            return Response(content=b"", status_code=HTTPStatus.UNAUTHORIZED)

        parse_result = self._getscores_parser.parse(request.query_params)
        if parse_result.error is not None or parse_result.request is None:
            error_value = parse_result.error.value if parse_result.error is not None else None
            logger.info(
                "getscores_identity_invalid",
                parse_error=error_value,
                user_id=auth_result.user_id,
            )
            return format_getscores_unavailable_response()

        request_obj = parse_result.request
        if request_obj.parse_warnings:
            logger.info(
                "getscores_parse_warning",
                warnings=[w.value for w in request_obj.parse_warnings],
                user_id=auth_result.user_id,
            )
        if request_obj.anti_cheat_signal:
            logger.info(
                "getscores_anti_cheat_signal",
                user_id=auth_result.user_id,
            )

        outcome = await self._getscores_query.resolve(request_obj)

        if outcome.kind is GetscoresOutcomeKind.UNAVAILABLE:
            logger.info(
                "getscores_unavailable",
                resolve_reason=outcome.reason.value,
                user_id=auth_result.user_id,
            )
            return format_getscores_unavailable_response()

        if outcome.kind is GetscoresOutcomeKind.UPDATE_AVAILABLE:
            logger.info(
                "getscores_update_available",
                resolve_reason=outcome.reason.value,
                user_id=auth_result.user_id,
            )
            return format_getscores_update_available_response()

        # HEADER outcome
        assert outcome.header is not None  # invariant for HEADER outcomes
        wire_status = self._status_mapper.map_header_status(outcome.header.beatmap)
        if wire_status is None:
            logger.info(
                "getscores_unavailable",
                resolve_reason=outcome.reason.value,
                user_id=auth_result.user_id,
            )
            return format_getscores_unavailable_response()

        return format_getscores_header_response(
            status=wire_status,
            beatmap=outcome.header.beatmap,
            beatmapset=outcome.header.beatmapset,
        )


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
) -> Response:
    artist = _sanitize(beatmapset.artist)
    title = _sanitize(beatmapset.title)

    body = (
        f"{status}|false|{beatmap.id}|{beatmap.beatmapset_id}|0||\n"
        f"0\n"
        f"[bold:0,size:20]{artist}|{title}\n"
        f"0\n"
        f"\n"
        f"\n"
    ).encode()
    return Response(
        content=body,
        status_code=HTTPStatus.OK,
        media_type=_TEXT_PLAIN_UTF8,
    )

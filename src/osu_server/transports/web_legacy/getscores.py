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

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.domain.beatmap import Beatmap, BeatmapSet
    from osu_server.services.legacy_getscores_service import LegacyGetscoresService
    from osu_server.services.legacy_web_auth_service import LegacyWebAuthService

_TEXT_PLAIN_UTF8 = "text/plain; charset=utf-8"

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


def _sanitize(text: str) -> str:
    return text.replace("|", " ").replace("\r", " ").replace("\n", " ")


class GetscoresFormatter:
    def format_unavailable(self) -> bytes:
        return b"-1|false"

    def format_update_available(self) -> bytes:
        return b"1|false"

    def format_header(
        self,
        *,
        status: int,
        beatmap: Beatmap,
        beatmapset: BeatmapSet,
    ) -> bytes:
        artist = _sanitize(beatmapset.artist)
        title = _sanitize(beatmapset.title)

        return (
            f"{status}|false|{beatmap.id}|{beatmap.beatmapset_id}|0||\n"
            f"0\n"
            f"[bold:0,size:20]{artist}|{title}\n"
            f"0\n"
            f"\n"
            f"\n"
        ).encode()


class GetscoresHandler:
    """Starlette handler for ``GET /web/osu-osz2-getscores.php``.

    Receives DI dependencies in ``__init__`` and acts as a callable ASGI
    endpoint via ``__call__``.
    """

    _auth_service: LegacyWebAuthService
    _getscores_service: LegacyGetscoresService
    _formatter: GetscoresFormatter

    def __init__(
        self,
        *,
        auth_service: LegacyWebAuthService,
        getscores_service: LegacyGetscoresService,
        formatter: GetscoresFormatter | None = None,
    ) -> None:
        self._auth_service = auth_service
        self._getscores_service = getscores_service
        self._formatter = formatter or GetscoresFormatter()

    async def __call__(self, request: Request) -> Response:
        """Handle a getscores request, returning the stable wire body."""
        username = request.query_params.get("us")
        password_md5 = request.query_params.get("ha")

        auth_result = await self._auth_service.authenticate(
            username=username,
            password_md5=password_md5,
        )
        if auth_result.failure is not None:
            _logger.info(
                "getscores_auth_failed",
                failure_reason=auth_result.failure.value,
            )
            return Response(content=b"", status_code=HTTPStatus.UNAUTHORIZED)

        parse_result = self._getscores_service.parse(request.query_params)
        if parse_result.error is not None or parse_result.request is None:
            error_value = parse_result.error.value if parse_result.error is not None else None
            _logger.info(
                "getscores_identity_invalid",
                parse_error=error_value,
                user_id=auth_result.user_id,
            )
            return Response(
                content=self._formatter.format_unavailable(),
                status_code=HTTPStatus.OK,
                media_type=_TEXT_PLAIN_UTF8,
            )

        request_obj = parse_result.request
        if request_obj.parse_warnings:
            _logger.info(
                "getscores_parse_warning",
                warnings=[w.value for w in request_obj.parse_warnings],
                user_id=auth_result.user_id,
            )
        if request_obj.anti_cheat_signal:
            _logger.info(
                "getscores_anti_cheat_signal",
                user_id=auth_result.user_id,
            )

        outcome = await self._getscores_service.resolve(request_obj)

        if outcome.kind is GetscoresOutcomeKind.UNAVAILABLE:
            _logger.info(
                "getscores_unavailable",
                resolve_reason=outcome.reason.value,
                user_id=auth_result.user_id,
            )
            return Response(
                content=self._formatter.format_unavailable(),
                status_code=HTTPStatus.OK,
                media_type=_TEXT_PLAIN_UTF8,
            )

        if outcome.kind is GetscoresOutcomeKind.UPDATE_AVAILABLE:
            _logger.info(
                "getscores_update_available",
                resolve_reason=outcome.reason.value,
                user_id=auth_result.user_id,
            )
            return Response(
                content=self._formatter.format_update_available(),
                status_code=HTTPStatus.OK,
                media_type=_TEXT_PLAIN_UTF8,
            )

        # HEADER outcome
        assert outcome.header is not None  # invariant for HEADER outcomes
        wire_status = self._getscores_service.map_header_status(outcome.header.beatmap)
        if wire_status is None:
            _logger.info(
                "getscores_unavailable",
                resolve_reason=outcome.reason.value,
                user_id=auth_result.user_id,
            )
            return Response(
                content=self._formatter.format_unavailable(),
                status_code=HTTPStatus.OK,
                media_type=_TEXT_PLAIN_UTF8,
            )

        body = self._formatter.format_header(
            status=wire_status,
            beatmap=outcome.header.beatmap,
            beatmapset=outcome.header.beatmapset,
        )
        return Response(
            content=body,
            status_code=HTTPStatus.OK,
            media_type=_TEXT_PLAIN_UTF8,
        )

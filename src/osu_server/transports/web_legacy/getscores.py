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

from osu_server.transports.web_legacy.getscores_resolver import GetscoresOutcomeKind

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.services.legacy_web_auth_service import LegacyWebAuthService
    from osu_server.transports.web_legacy.getscores_formatter import GetscoresFormatter
    from osu_server.transports.web_legacy.getscores_query_parser import (
        GetscoresQueryParser,
    )
    from osu_server.transports.web_legacy.getscores_resolver import GetscoresResolver
    from osu_server.transports.web_legacy.getscores_status_mapper import (
        GetscoresStatusMapper,
    )

_TEXT_PLAIN_UTF8 = "text/plain; charset=utf-8"

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class GetscoresHandler:
    """Starlette handler for ``GET /web/osu-osz2-getscores.php``.

    Receives DI dependencies in ``__init__`` and acts as a callable ASGI
    endpoint via ``__call__``.
    """

    _auth_service: LegacyWebAuthService
    _parser: GetscoresQueryParser
    _resolver: GetscoresResolver
    _formatter: GetscoresFormatter
    _status_mapper: GetscoresStatusMapper

    def __init__(
        self,
        *,
        auth_service: LegacyWebAuthService,
        parser: GetscoresQueryParser,
        resolver: GetscoresResolver,
        formatter: GetscoresFormatter,
        status_mapper: GetscoresStatusMapper,
    ) -> None:
        self._auth_service = auth_service
        self._parser = parser
        self._resolver = resolver
        self._formatter = formatter
        self._status_mapper = status_mapper

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

        parse_result = self._parser.parse(request.query_params)
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

        outcome = await self._resolver.resolve(request_obj)

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
        wire_status = self._status_mapper.map_header_status(outcome.header.beatmap)
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

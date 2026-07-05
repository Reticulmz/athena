"""HTTP request logging middleware."""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol, cast

import structlog
import structlog.contextvars
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from osu_server.config import AppConfig
from osu_server.infrastructure.database.query_diagnostics import (
    QueryDiagnosticSummary,
    query_diagnostic_scope,
    query_diagnostics_exceeded,
    query_diagnostics_warning_fields,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]


class _ConfigState(Protocol):
    config: object


class _ConfigApp(Protocol):
    state: _ConfigState


class SQLQueryDiagnosticsMiddleware(BaseHTTPMiddleware):
    """HTTP request ごとに SQL query diagnostics scope を開く middleware."""

    async def dispatch(  # pyright: ignore[reportImplicitOverride]
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Development runtime で SQL query diagnostics warning を出す.

        Args:
            request: Starlette request.
            call_next: 次の middleware または endpoint を呼び出す callable.

        Returns:
            後続処理が返した response.
        """
        config = _get_request_config(request)
        if config is None or not config.query_diagnostics_effective_enabled:
            return await call_next(request)

        with query_diagnostic_scope(
            scope_kind="http_request",
            scope_name=f"{request.method} {request.url.path}",
            duplicate_threshold=config.query_diagnostics_duplicate_threshold,
        ) as collector:
            try:
                return await call_next(request)
            finally:
                await _emit_sql_query_diagnostics_warning(
                    collector.summary(),
                    max_queries=config.query_diagnostics_max_queries,
                )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, and duration.

    Clears ``structlog.contextvars`` at the start of each request so that
    context bound during one request (e.g. ``user``, ``user_id``) does not
    leak into subsequent requests.
    """

    async def dispatch(  # pyright: ignore[reportImplicitOverride]
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Record an ``http_request`` event after the response is produced.

        Uses ``try/finally`` so that unhandled exceptions are still logged
        (with ``status=500``) before propagating.
        """
        structlog.contextvars.clear_contextvars()

        start = time.perf_counter()
        status = int(HTTPStatus.INTERNAL_SERVER_ERROR)
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            if not (
                request.url.path == "/health"
                and HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES
            ):
                await logger.ainfo(
                    "http_request",
                    host=request.url.hostname,
                    method=request.method,
                    path=request.url.path,
                    status=status,
                    duration_ms=round(duration_ms, 2),
                )
        return response


def _get_request_config(request: Request) -> AppConfig | None:
    try:
        config = cast("_ConfigApp", request.app).state.config
    except AttributeError:
        return None
    if isinstance(config, AppConfig):
        return config
    return None


async def _emit_sql_query_diagnostics_warning(
    summary: QueryDiagnosticSummary,
    *,
    max_queries: int,
) -> None:
    if not query_diagnostics_exceeded(summary, max_queries=max_queries):
        return
    try:
        await logger.awarning(
            "sql_query_diagnostics_warning",
            **query_diagnostics_warning_fields(summary, max_queries=max_queries),
        )
    except Exception:
        return

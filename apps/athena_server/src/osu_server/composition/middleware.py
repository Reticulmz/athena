"""HTTP request loggingとSQL query diagnosticsのmiddlewareを提供する.

requestごとのdiagnostic scopeとstructured logをapplication middleware chainへ追加する.
"""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol, cast, override

import structlog
import structlog.contextvars
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from osu_server.config import AppConfig
from osu_server.shared.query_diagnostics import (
    emit_sql_query_diagnostics_warning,
    query_diagnostic_scope,
)

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]


class _ConfigState(Protocol):
    """middlewareが要求するconfiguration stateを表す.

    Attributes:
        config (object): application lifespanが設定するruntime configuration候補.
    """

    config: object


class _ConfigApp(Protocol):
    """middlewareが要求するapplication interfaceを表す.

    Attributes:
        state (_ConfigState): runtime configurationを保持するapplication state.
    """

    state: _ConfigState


class SQLQueryDiagnosticsMiddleware(BaseHTTPMiddleware):
    """HTTP requestごとにSQL query diagnostics scopeを開くmiddlewareを表す."""

    @override
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """開発runtimeでSQL query diagnostics warningを出す.

        Args:
            request (Request): 診断scope名とruntime configurationを取得するStarlette request.
            call_next (RequestResponseEndpoint): 次のmiddlewareまたはendpointを呼び出すcallable.

        Returns:
            Response: 後続処理が返したresponse.
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
                await emit_sql_query_diagnostics_warning(
                    logger,
                    collector.summary(),
                    max_queries=config.query_diagnostics_max_queries,
                )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """HTTP requestのmethod,path,status,durationをstructured logへ記録する.

    各requestの開始時に`structlog.contextvars`をclearし,前requestでbindしたuser contextが
    次requestへ漏れないようにする.
    """

    async def dispatch(  # pyright: ignore[reportImplicitOverride]
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """response生成後に`http_request` eventを記録する.

        Args:
            request (Request): logにhost,method,pathを記録するStarlette request.
            call_next (RequestResponseEndpoint): 次のmiddlewareまたはendpointを呼び出すcallable.

        Returns:
            Response: 後続処理が返したresponse.
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
    """アプリケーションstateから有効なAppConfigだけを取り出す.

    Args:
        request (Request): application stateを持つStarlette request.

    Returns:
        AppConfig | None: stateにAppConfigが設定済みならその値. state未設定または別型ならNone.
    """
    try:
        config = cast("_ConfigApp", request.app).state.config
    except AttributeError:
        return None
    if isinstance(config, AppConfig):
        return config
    return None

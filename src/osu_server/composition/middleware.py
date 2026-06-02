"""HTTP request logging middleware."""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING

import structlog
import structlog.contextvars
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]


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

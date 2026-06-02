"""Tests for RequestLoggingMiddleware.

Validates:
- Req 4.1: HTTP requests are logged with method, path, status, duration_ms
- Req 5.1: structlog is used for all logging
- Req 5.3: Sensitive contextvars are cleared between requests
- Req 7.1: contextvars user info appears in log entries after binding

Uses a minimal Starlette app with the middleware applied and
structlog.testing.capture_logs() for log assertions.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import structlog
import structlog.contextvars
import structlog.testing
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.app import RequestLoggingMiddleware

if TYPE_CHECKING:
    from starlette.requests import Request


# ── Helpers ──────────────────────────────────────────────────────────


async def _ok_endpoint(_request: Request) -> PlainTextResponse:
    """Simple 200 OK endpoint."""
    return PlainTextResponse("ok")


async def _error_endpoint(_request: Request) -> PlainTextResponse:
    """Returns 500 Internal Server Error."""
    return PlainTextResponse("error", status_code=HTTPStatus.INTERNAL_SERVER_ERROR)


async def _raise_endpoint(_request: Request) -> PlainTextResponse:
    """Endpoint that raises an unhandled exception."""
    msg = "unhandled"
    raise RuntimeError(msg)


async def _bind_user_endpoint(_request: Request) -> PlainTextResponse:
    """Endpoint that binds user info to structlog contextvars."""
    _ = structlog.contextvars.bind_contextvars(user="TestUser", user_id=42)
    return PlainTextResponse("ok")


def _make_app(
    routes: list[Route] | None = None,
) -> Starlette:
    """Build a minimal Starlette app with RequestLoggingMiddleware."""
    if routes is None:
        routes = [
            Route("/", endpoint=_ok_endpoint, methods=["GET", "POST"]),
            Route("/error", endpoint=_error_endpoint, methods=["GET"]),
            Route("/raise", endpoint=_raise_endpoint, methods=["GET"]),
            Route("/bind", endpoint=_bind_user_endpoint, methods=["GET"]),
        ]
    return Starlette(
        routes=routes,
        middleware=[Middleware(RequestLoggingMiddleware)],
    )


# ═══════════════════════════════════════════════════════════════════════
# Req 4.1: HTTP request logging with method, path, status, duration_ms
# ═══════════════════════════════════════════════════════════════════════


class TestRequestLoggingMiddleware:
    """Middleware logs every HTTP request with expected fields."""

    def test_logs_get_request(self) -> None:
        """GET request produces an http_request log entry."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert len(http_logs) == 1

    def test_logs_post_request(self) -> None:
        """POST request produces an http_request log entry."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.post("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert len(http_logs) == 1

    def test_log_contains_method(self) -> None:
        """Log entry includes the HTTP method."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["method"] == "GET"

    def test_log_contains_post_method(self) -> None:
        """POST method is correctly recorded."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.post("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["method"] == "POST"

    def test_log_contains_path(self) -> None:
        """Log entry includes the request path."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["path"] == "/"

    def test_log_contains_status_code(self) -> None:
        """Log entry includes the response status code."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["status"] == HTTPStatus.OK

    def test_log_contains_error_status_code(self) -> None:
        """Error status codes are correctly recorded."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/error")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["status"] == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_log_contains_duration_ms(self) -> None:
        """Log entry includes duration_ms as a non-negative number."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert "duration_ms" in http_logs[0]
        assert isinstance(http_logs[0]["duration_ms"], float)
        assert http_logs[0]["duration_ms"] >= 0

    def test_log_level_is_info(self) -> None:
        """HTTP request log entries are logged at INFO level."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["log_level"] == "info"

    def test_multiple_requests_produce_multiple_logs(self) -> None:
        """Each request produces its own log entry."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")
            _ = client.post("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert len(http_logs) == 2

    def test_health_2xx_request_is_not_logged(self) -> None:
        """Successful health probes do not produce access log noise."""
        app = _make_app(routes=[Route("/health", endpoint=_ok_endpoint, methods=["GET"])])
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/health")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs == []

    def test_health_error_request_is_logged(self) -> None:
        """Failed health probes remain visible in request logs."""
        app = _make_app(routes=[Route("/health", endpoint=_error_endpoint, methods=["GET"])])
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/health")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert len(http_logs) == 1
        assert http_logs[0]["path"] == "/health"
        assert http_logs[0]["status"] == HTTPStatus.INTERNAL_SERVER_ERROR


# ═══════════════════════════════════════════════════════════════════════
# Req 5.3 / 7.1: contextvars cleared between requests
# ═══════════════════════════════════════════════════════════════════════


class TestRequestLoggingContextvars:
    """Middleware clears contextvars between requests to prevent leaking."""

    def test_contextvars_cleared_between_requests(self) -> None:
        """User context bound in one request does not leak to the next."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            # First request binds user context
            _ = client.get("/bind")
            # Second request should NOT have user context
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert len(http_logs) == 2

        # The second request's log should not contain the user key
        # from the first request (contextvars cleared by middleware)
        second_log = http_logs[1]
        assert "user" not in second_log
        assert "user_id" not in second_log

    def test_contextvars_present_during_request(self) -> None:
        """User context bound during a request is accessible within that request.

        capture_logs() replaces the processor chain so merge_contextvars
        does not run, but we can verify the binding happened by inspecting
        structlog.contextvars state from the endpoint itself.
        """
        captured_ctx: dict[str, object] = {}

        async def _capture_ctx_endpoint(_request: Request) -> PlainTextResponse:
            _ = structlog.contextvars.bind_contextvars(user="TestUser", user_id=42)
            captured_ctx.update(structlog.contextvars.get_contextvars())
            return PlainTextResponse("ok")

        app = _make_app(
            routes=[Route("/ctx", endpoint=_capture_ctx_endpoint, methods=["GET"])],
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            _ = client.get("/ctx")

        assert captured_ctx["user"] == "TestUser"
        assert captured_ctx["user_id"] == 42


# ═══════════════════════════════════════════════════════════════════════
# Unhandled exception logging
# ═══════════════════════════════════════════════════════════════════════


class TestRequestLoggingOnException:
    """Middleware logs the request even when the endpoint raises."""

    def test_logs_with_status_500_on_unhandled_exception(self) -> None:
        """Unhandled endpoint exception still produces an http_request log with status=500."""
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/raise")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert len(http_logs) == 1
        assert http_logs[0]["status"] == 500
        assert http_logs[0]["method"] == "GET"
        assert http_logs[0]["path"] == "/raise"
        assert http_logs[0]["duration_ms"] >= 0

"""RequestLoggingMiddlewareのrequest logとcontextvars contractを検証する."""

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
    """HTTP 200とok bodyを返すtest endpointを提供する.

    Args:
        _request (Request): Starletteから渡されるHTTP request.

    Returns:
        PlainTextResponse: status code 200を持つok response.
    """
    return PlainTextResponse("ok")


async def _error_endpoint(_request: Request) -> PlainTextResponse:
    """HTTP 500とerror bodyを返すtest endpointを提供する.

    Args:
        _request (Request): Starletteから渡されるHTTP request.

    Returns:
        PlainTextResponse: status code 500を持つerror response.
    """
    return PlainTextResponse("error", status_code=HTTPStatus.INTERNAL_SERVER_ERROR)


async def _raise_endpoint(_request: Request) -> PlainTextResponse:
    """Unhandled RuntimeErrorを送出するtest endpointを提供する.

    Args:
        _request (Request): Starletteから渡されるHTTP request.

    Raises:
        RuntimeError: middlewareのexception logを検証するため常に送出する.
    """
    msg = "unhandled"
    raise RuntimeError(msg)


async def _bind_user_endpoint(_request: Request) -> PlainTextResponse:
    """User情報をstructlog contextvarsへbindするtest endpointを提供する.

    Args:
        _request (Request): Starletteから渡されるHTTP request.

    Returns:
        PlainTextResponse: user contextをbindした後のok response.
    """
    _ = structlog.contextvars.bind_contextvars(user="TestUser", user_id=42)
    return PlainTextResponse("ok")


def _make_app(
    routes: list[Route] | None = None,
) -> Starlette:
    """RequestLoggingMiddlewareを持つminimal Starlette appを構築する.

    Args:
        routes (list[Route] | None): 使用するroute一覧. Noneなら既定test routeを使う.

    Returns:
        Starlette: request logging middlewareを適用したtest app.
    """
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
    """HTTP requestのmethod, path, status, durationをlogへ記録するcontractを検証する."""

    def test_logs_get_request(self) -> None:
        """GET requestがhttp_request logを1件生成するcontractを検証する.

        Returns:
            None: captureしたhttp_request log数を確認して完了する.
        """
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert len(http_logs) == 1

    def test_logs_post_request(self) -> None:
        """POST requestがhttp_request logを1件生成するcontractを検証する.

        Returns:
            None: captureしたhttp_request log数を確認して完了する.
        """
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.post("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert len(http_logs) == 1

    def test_log_contains_method(self) -> None:
        """Request logがGET methodを保持するcontractを検証する.

        Returns:
            None: method fieldがGETとなることを確認して完了する.
        """
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["method"] == "GET"

    def test_log_contains_post_method(self) -> None:
        """Request logがPOST methodを保持するcontractを検証する.

        Returns:
            None: method fieldがPOSTとなることを確認して完了する.
        """
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.post("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["method"] == "POST"

    def test_log_contains_path(self) -> None:
        """Request logがrequest pathを保持するcontractを検証する.

        Returns:
            None: path fieldがroot pathとなることを確認して完了する.
        """
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["path"] == "/"

    def test_log_contains_status_code(self) -> None:
        """Request logがsuccessful responseのstatus codeを保持するcontractを検証する.

        Returns:
            None: status fieldがHTTP 200となることを確認して完了する.
        """
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["status"] == HTTPStatus.OK

    def test_log_contains_error_status_code(self) -> None:
        """Request logがerror responseのstatus codeを保持するcontractを検証する.

        Returns:
            None: status fieldがHTTP 500となることを確認して完了する.
        """
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/error")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["status"] == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_log_contains_duration_ms(self) -> None:
        """Request logがnon-negative floatのduration_msを保持するcontractを検証する.

        Returns:
            None: duration_ms fieldの型と下限を確認して完了する.
        """
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
        """HTTP request logがinfo levelで出力されるcontractを検証する.

        Returns:
            None: log_level fieldがinfoとなることを確認して完了する.
        """
        app = _make_app()
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs[0]["log_level"] == "info"

    def test_multiple_requests_produce_multiple_logs(self) -> None:
        """複数requestが独立したrequest logを生成するcontractを検証する.

        Returns:
            None: GETとPOSTに対応するlogが2件あることを確認して完了する.
        """
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
        """Successful health probeをaccess logへ出さないcontractを検証する.

        Returns:
            None: GET /healthのHTTP 200時にrequest logがないことを確認して完了する.
        """
        app = _make_app(routes=[Route("/health", endpoint=_ok_endpoint, methods=["GET"])])
        with (
            structlog.testing.capture_logs() as logs,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            _ = client.get("/health")

        http_logs = [log for log in logs if log["event"] == "http_request"]
        assert http_logs == []

    def test_health_error_request_is_logged(self) -> None:
        """Failed health probeをaccess logへ残すcontractを検証する.

        Returns:
            None: GET /healthのHTTP 500時にpathとstatusを持つlogを確認して完了する.
        """
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
    """Request間のcontextvars leak防止とrequest内bindingを検証する."""

    def test_contextvars_cleared_between_requests(self) -> None:
        """前requestでbindしたuser contextが次requestへleakしないcontractを検証する.

        Returns:
            None: 2件目のrequest logにuser fieldがないことを確認して完了する.
        """
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
        """Request内でbindしたuser contextがendpointから参照できるcontractを検証する.

        Returns:
            None: endpoint内でcaptureしたuserとuser_idを確認して完了する.

        Notes:
            capture_logsはprocessor chainを置換するためendpoint内のcontextvarsを直接検査する.
        """
        captured_ctx: dict[str, object] = {}

        async def _capture_ctx_endpoint(_request: Request) -> PlainTextResponse:
            """User contextをbindしてcapture mappingへ保存するnested test endpointを提供する.

            Args:
                _request (Request): Starletteから渡されるHTTP request.

            Returns:
                PlainTextResponse: context capture後のok response.
            """
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
    """Endpoint exception時にもrequest logを残すcontractを検証する."""

    def test_logs_with_status_500_on_unhandled_exception(self) -> None:
        """Unhandled endpoint exceptionがHTTP 500 request logを生成するcontractを検証する.

        Returns:
            None: status, method, path, durationを持つerror logを確認して完了する.
        """
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

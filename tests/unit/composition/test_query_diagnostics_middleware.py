"""HTTP SQL query diagnostics middleware の runtime 契約を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog.testing
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from tests.factories.config import make_app_config

from osu_server.composition.middleware import SQLQueryDiagnosticsMiddleware
from osu_server.shared.query_diagnostics import record_query

if TYPE_CHECKING:
    from starlette.requests import Request


async def _sql_endpoint(request: Request) -> PlainTextResponse:
    """秘密値を含む二つの query を記録して成功 response を返す test endpoint.

    Args:
        request (Request): diagnostics middleware を通過した HTTP request.

    Returns:
        PlainTextResponse: query 記録後の固定成功 response.
    """
    _ = request
    record_query(
        "SELECT * FROM users WHERE email = 'secret@example.invalid' AND id = 123",
        parameters={"email": "secret@example.invalid", "token": "secret-token"},
    )
    record_query(
        "SELECT * FROM users WHERE email = 'other@example.invalid' AND id = 456",
        parameters={"email": "secret@example.invalid", "token": "secret-token"},
    )
    return PlainTextResponse("ok")


def _make_app(*, environment: str, enabled: bool | None = None) -> Starlette:
    """指定した diagnostics 設定で middleware を持つ test app を作る.

    Args:
        environment (str): AppConfig に設定する実行環境.
        enabled (bool | None): diagnostics 有効状態の明示 override. None は既定に委ねる.

    Returns:
        Starlette: diagnostics endpoint と middleware を設定済みの app.
    """
    app = Starlette(
        routes=[Route("/diagnostics", _sql_endpoint)],
        middleware=[Middleware(SQLQueryDiagnosticsMiddleware)],
    )
    app.state.config = make_app_config(
        environment=environment,
        query_diagnostics_enabled=enabled,
        query_diagnostics_max_queries=1,
        query_diagnostics_duplicate_threshold=2,
    )
    return app


def test_http_sql_query_diagnostics_warns_in_development() -> None:
    """開発 request の query 数超過時に秘密値を伏せた warning を出す契約を検証する.

    Returns:
        None: HTTP response, warning 集計値, redaction 後 template を検証して完了する.
    """
    app = _make_app(environment="development")

    with structlog.testing.capture_logs() as logs, TestClient(app) as client:
        response = client.get("/diagnostics?token=secret-token")

    assert response.status_code == 200
    warning = next(log for log in logs if log["event"] == "sql_query_diagnostics_warning")
    assert warning["scope_kind"] == "http_request"
    assert warning["scope_name"] == "GET /diagnostics"
    assert warning["total_queries"] == 2
    assert warning["max_queries"] == 1
    assert warning["duplicate_templates_total"] == 1
    assert warning["duplicates_truncated"] is False
    assert "secret-token" not in repr(warning)
    assert "secret@example.invalid" not in repr(warning)
    assert "SELECT * FROM users WHERE email = ? AND id = ?" in repr(warning)


def test_http_sql_query_diagnostics_skips_non_development_default() -> None:
    """本番既定では query を記録しても runtime warning を出さない契約を検証する.

    Returns:
        None: HTTP 成功 response と warning 不在を検証して完了する.
    """
    app = _make_app(environment="production")

    with structlog.testing.capture_logs() as logs, TestClient(app) as client:
        response = client.get("/diagnostics?token=secret-token")

    assert response.status_code == 200
    assert not [log for log in logs if log["event"] == "sql_query_diagnostics_warning"]


def test_http_sql_query_diagnostics_respects_disabled_override() -> None:
    """開発環境でも明示的 disabled override が runtime warning を抑止する契約を検証する.

    Returns:
        None: HTTP 成功 response と warning 不在を検証して完了する.
    """
    app = _make_app(environment="development", enabled=False)

    with structlog.testing.capture_logs() as logs, TestClient(app) as client:
        response = client.get("/diagnostics")

    assert response.status_code == 200
    assert not [log for log in logs if log["event"] == "sql_query_diagnostics_warning"]

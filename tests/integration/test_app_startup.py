# pyright: reportUnknownMemberType=false, reportAny=false
"""E2E integration tests for Starlette application startup and lifecycle.

Verifies that the app starts correctly via lifespan, responds to requests,
and shuts down cleanly.  Requires running PostgreSQL and Redis instances.
"""

import os
from http import HTTPStatus

import pytest
from starlette.testclient import TestClient

from osu_server.app import create_app
from osu_server.config import AppConfig
from osu_server.infrastructure.di.container import Container


def _require_services() -> None:
    """Skip the test suite if DATABASE_URL or REDIS_URL are not set."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    if not os.environ.get("REDIS_URL"):
        pytest.skip("REDIS_URL not set")


class TestAppStartup:
    """E2E tests for application lifecycle via Starlette TestClient."""

    def test_app_starts_and_responds(self) -> None:
        """POST / returns 200 when the app is running."""
        _require_services()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/")
            assert response.status_code == HTTPStatus.OK

    def test_lifespan_sets_state(self) -> None:
        """After startup, app.state.container and app.state.config are set."""
        _require_services()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False):
            assert hasattr(app.state, "config")
            assert hasattr(app.state, "container")
            assert isinstance(app.state.config, AppConfig)
            assert isinstance(app.state.container, Container)

    def test_get_root_returns_method_not_allowed(self) -> None:
        """GET / returns 405 because only POST is allowed on the root route."""
        _require_services()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/")
            assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

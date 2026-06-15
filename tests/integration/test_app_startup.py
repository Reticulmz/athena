"""E2E integration tests for Starlette application startup and lifecycle.

Verifies that the app starts correctly via lifespan, responds to requests,
and shuts down cleanly.  Requires running PostgreSQL and Redis instances.
"""

import os
from http import HTTPStatus
from typing import cast

import pytest
from dishka import AsyncContainer
from starlette.testclient import TestClient

from osu_server.app import create_app
from osu_server.config import AppConfig


def _require_services() -> None:
    """Skip the test suite if DATABASE_URL or REDIS_URL are not set."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    if not os.environ.get("VALKEY_URL"):
        pytest.skip("VALKEY_URL not set")


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
        """After startup, app.state.dishka_container and app.state.config are set."""
        _require_services()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False):
            assert hasattr(app.state, "config")
            assert hasattr(app.state, "dishka_container")
            assert isinstance(cast("object", app.state.config), AppConfig)
            assert isinstance(cast("object", app.state.dishka_container), AsyncContainer)

    def test_get_root_returns_ok(self) -> None:
        """GET / returns 200 — bancho handler accepts GET for connectivity probes."""
        _require_services()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/")
            assert response.status_code == HTTPStatus.OK

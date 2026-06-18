"""E2E integration tests for Starlette application startup and lifecycle."""

from http import HTTPStatus
from pathlib import Path
from typing import cast

from dishka import AsyncContainer
from starlette.testclient import TestClient

from osu_server.app import create_app as create_runtime_app
from osu_server.config import AppConfig, load_routing_config
from tests.support.app import create_in_memory_app
from tests.support.service_availability import require_tcp_service_url

_BANCHO_URL = f"http://c.{load_routing_config().domain}/"


def _require_services() -> None:
    """Skip the test suite if required external services are unavailable."""
    _ = require_tcp_service_url("DATABASE_URL", default_port=5432)
    _ = require_tcp_service_url("VALKEY_URL", default_port=6379)


class TestInMemoryAppStartup:
    """App lifecycle tests that do not require external services."""

    def test_app_starts_and_responds(self, tmp_path: Path) -> None:
        """POST / on the bancho host returns 200 when the app is running."""
        app = create_in_memory_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(_BANCHO_URL)
            assert response.status_code == HTTPStatus.OK

    def test_lifespan_sets_state(self, tmp_path: Path) -> None:
        """After startup, app.state.dishka_container and app.state.config are set."""
        app = create_in_memory_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False):
            assert hasattr(app.state, "config")
            assert hasattr(app.state, "dishka_container")
            assert isinstance(cast("object", app.state.config), AppConfig)
            assert isinstance(cast("object", app.state.dishka_container), AsyncContainer)

    def test_get_root_returns_ok(self, tmp_path: Path) -> None:
        """GET / returns 200 — bancho handler accepts GET for connectivity probes."""
        app = create_in_memory_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/")
            assert response.status_code == HTTPStatus.OK


class TestRuntimeAppStartupSmoke:
    """Production provider graph smoke tests that require external services."""

    def test_runtime_app_get_root_returns_ok(self) -> None:
        """GET / works with the production provider graph when services are available."""
        _require_services()
        app = create_runtime_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/")
            assert response.status_code == HTTPStatus.OK

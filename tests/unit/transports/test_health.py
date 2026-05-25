"""Health endpoint unit tests (Req 4.1, 4.2, 4.3).

Verifies that GET / on bancho and web_legacy routes returns:
- Status 200 with Content-Type: text/plain
- Body format: "athena v{version} ({commit_hash})\n"
- Version number from pyproject.toml (0.1.0)
- Commit hash or "unknown" fallback
"""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.app import _health_check_endpoint, _health_endpoint, get_version_info
from osu_server.config import AppConfig

if TYPE_CHECKING:
    import pytest

# ── Constants ──────────────────────────────────────────────────────────

_OK = HTTPStatus.OK
_UNAVAILABLE = HTTPStatus.SERVICE_UNAVAILABLE
_HEALTH_PATTERN = re.compile(r"^athena v[\d.]+ \(\w+\)\n$")


# ═══════════════════════════════════════════════════════════════════════
# get_version_info (Req 4.3)
# ═══════════════════════════════════════════════════════════════════════


class TestGetVersionInfo:
    """Version info tuple contains package version and commit hash."""

    def test_version_contains_pyproject_version(self) -> None:
        """Version string includes the pyproject.toml version (0.1.0)."""
        version, _commit = get_version_info()
        assert version == "0.1.0"

    def test_commit_hash_is_string(self) -> None:
        """Commit hash is a non-empty string."""
        _version, commit = get_version_info()
        assert isinstance(commit, str)
        assert len(commit) > 0

    def test_commit_hash_or_unknown(self) -> None:
        """Commit hash is either a hex string or 'unknown'."""
        _version, commit = get_version_info()
        assert commit == "unknown" or re.match(r"^[0-9a-f]+$", commit)

    def test_fallback_to_unknown_on_git_failure(self) -> None:
        """When git is unavailable, commit hash falls back to 'unknown'."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            _version, commit = get_version_info()
            assert commit == "unknown"


# ═══════════════════════════════════════════════════════════════════════
# _health_endpoint (Req 4.1, 4.2)
# ═══════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    """GET / returns health response with version info."""

    @staticmethod
    def _make_app(version: str = "0.1.0", commit: str = "abc1234") -> Starlette:
        """Build a minimal app with _health_endpoint and version_info on state."""
        app = Starlette(routes=[Route("/", _health_endpoint, methods=["GET"])])
        app.state.version_info = (version, commit)
        return app

    def test_returns_200(self) -> None:
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == _OK

    def test_content_type_is_text_plain(self) -> None:
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/")
            assert "text/plain" in resp.headers["content-type"]

    def test_body_contains_version(self) -> None:
        app = self._make_app(version="0.1.0")
        with TestClient(app) as client:
            resp = client.get("/")
            assert "v0.1.0" in resp.text

    def test_body_contains_commit_hash(self) -> None:
        app = self._make_app(commit="abc1234")
        with TestClient(app) as client:
            resp = client.get("/")
            assert "abc1234" in resp.text

    def test_body_matches_format(self) -> None:
        app = self._make_app(version="0.1.0", commit="abc1234")
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.text == "athena v0.1.0 (abc1234)\n"

    def test_body_with_unknown_commit(self) -> None:
        app = self._make_app(version="0.1.0", commit="unknown")
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.text == "athena v0.1.0 (unknown)\n"

    def test_body_matches_pattern(self) -> None:
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/")
            assert _HEALTH_PATTERN.match(resp.text)


# ═══════════════════════════════════════════════════════════════════════
# Config domain default (Req 3.1)
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# _health_check_endpoint (GET /health)
# ═══════════════════════════════════════════════════════════════════════


class TestHealthCheckEndpoint:
    """GET /health returns infrastructure health with DB and Valkey checks."""

    @staticmethod
    def _make_container(*, postgres_ok: bool = True, valkey_ok: bool = True) -> MagicMock:
        mock_conn = AsyncMock()
        if not postgres_ok:
            mock_conn.execute.side_effect = ConnectionError("pg down")

        mock_engine = MagicMock()
        cm = AsyncMock()
        cm.__aenter__.return_value = mock_conn
        cm.__aexit__.return_value = False
        mock_engine.connect.return_value = cm

        mock_valkey = AsyncMock()
        if not valkey_ok:
            mock_valkey.ping.side_effect = ConnectionError("valkey down")

        async def resolve(type_: type) -> object:
            if type_ is AsyncEngine:
                return mock_engine
            return mock_valkey

        container = MagicMock()
        container.resolve = AsyncMock(side_effect=resolve)
        return container

    @classmethod
    def _make_app(
        cls,
        version: str = "0.1.0",
        commit: str = "abc1234",
        *,
        postgres_ok: bool = True,
        valkey_ok: bool = True,
    ) -> Starlette:
        app = Starlette(routes=[Route("/health", _health_check_endpoint, methods=["GET"])])
        app.state.version_info = (version, commit)
        app.state.container = cls._make_container(postgres_ok=postgres_ok, valkey_ok=valkey_ok)
        return app

    def test_healthy_returns_200(self) -> None:
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == _OK

    def test_healthy_response_body(self) -> None:
        app = self._make_app(version="0.1.0", commit="abc1234")
        with TestClient(app) as client:
            data = client.get("/health").json()
            assert data["status"] == "healthy"
            assert data["version"] == "0.1.0"
            assert data["commit"] == "abc1234"
            assert data["checks"]["postgres"] == "ok"
            assert data["checks"]["valkey"] == "ok"

    def test_content_type_is_json(self) -> None:
        app = self._make_app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert "application/json" in resp.headers["content-type"]

    def test_postgres_down_returns_503(self) -> None:
        app = self._make_app(postgres_ok=False)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == _UNAVAILABLE
            data = resp.json()
            assert data["status"] == "unhealthy"
            assert data["checks"]["postgres"] == "error"
            assert data["checks"]["valkey"] == "ok"

    def test_valkey_down_returns_503(self) -> None:
        app = self._make_app(valkey_ok=False)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == _UNAVAILABLE
            data = resp.json()
            assert data["status"] == "unhealthy"
            assert data["checks"]["postgres"] == "ok"
            assert data["checks"]["valkey"] == "error"

    def test_both_down_returns_503(self) -> None:
        app = self._make_app(postgres_ok=False, valkey_ok=False)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == _UNAVAILABLE
            data = resp.json()
            assert data["status"] == "unhealthy"
            assert data["checks"]["postgres"] == "error"
            assert data["checks"]["valkey"] == "error"


# ═══════════════════════════════════════════════════════════════════════
# Config domain default (Req 3.1)
# ═══════════════════════════════════════════════════════════════════════


class TestConfigDomainDefault:
    """AppConfig.domain defaults to 'athena.localhost'."""

    def test_domain_default_is_athena_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/osu")
        monkeypatch.setenv("VALKEY_URL", "redis://localhost:6379/0")

        config = AppConfig()  # pyright: ignore[reportCallIssue]
        assert config.domain == "athena.localhost"

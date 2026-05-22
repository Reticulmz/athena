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
from unittest.mock import patch

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.app import _health_endpoint, get_version_info
from osu_server.config import AppConfig

if TYPE_CHECKING:
    import pytest

# ── Constants ──────────────────────────────────────────────────────────

_OK = HTTPStatus.OK
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


class TestConfigDomainDefault:
    """AppConfig.domain defaults to 'athena.local'."""

    def test_domain_default_is_athena_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/osu")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        config = AppConfig()  # pyright: ignore[reportCallIssue]
        assert config.domain == "athena.local"

"""Health and version endpoints for the root ASGI application."""

from __future__ import annotations

import importlib.metadata
import subprocess
from typing import TYPE_CHECKING

import structlog
from glide import GlideClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.responses import JSONResponse, PlainTextResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.infrastructure.di.container import Container

logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]


def get_version_info() -> tuple[str, str]:
    """Return ``(package_version, commit_hash)`` for health responses.

    * ``package_version`` comes from ``importlib.metadata`` (pyproject.toml).
    * ``commit_hash`` is the short git HEAD hash; falls back to ``"unknown"``
      when git is unavailable or the repo is missing.
    """
    version = importlib.metadata.version("athena")

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        commit = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        commit = "unknown"

    return version, commit


async def check_infrastructure(container: Container) -> None:
    """Verify PostgreSQL and Valkey connectivity at startup.

    Raises on failure so the server refuses to start with broken dependencies.
    """
    engine = await container.resolve(AsyncEngine)
    async with engine.connect() as conn:
        _ = await conn.execute(text("SELECT 1"))
    logger.info("startup_health_check", service="postgresql", status="ok")

    valkey = await container.resolve(GlideClient)
    _ = await valkey.ping()
    logger.info("startup_health_check", service="valkey", status="ok")


async def health_endpoint(request: Request) -> PlainTextResponse:
    """Return a plain-text health response with version and commit hash."""
    version, commit = request.app.state.version_info  # pyright: ignore[reportAny]
    return PlainTextResponse(f"athena v{version} ({commit})\n")


async def health_check_endpoint(request: Request) -> JSONResponse:
    """Return infrastructure health status with DB and Valkey connectivity checks."""
    version, commit = request.app.state.version_info  # pyright: ignore[reportAny]
    container: Container = request.app.state.container  # pyright: ignore[reportAny]

    checks: dict[str, str] = {}

    try:
        engine = await container.resolve(AsyncEngine)
        async with engine.connect() as conn:
            _ = await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error"

    try:
        valkey = await container.resolve(GlideClient)
        _ = await valkey.ping()
        checks["valkey"] = "ok"
    except Exception:
        checks["valkey"] = "error"

    all_healthy = all(v == "ok" for v in checks.values())

    return JSONResponse(
        {
            "status": "healthy" if all_healthy else "unhealthy",
            "version": version,
            "commit": commit,
            "checks": checks,
        },
        status_code=200 if all_healthy else 503,
    )

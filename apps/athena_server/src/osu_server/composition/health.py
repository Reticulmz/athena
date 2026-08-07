"""root ASGI applicationのversionとhealth endpointを提供する.

起動時のinfrastructure確認と,request時に返すversion/依存service状態をここで定義する.
"""

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
    from dishka import AsyncContainer
    from starlette.requests import Request

logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]


def get_version_info() -> tuple[str, str]:
    """応答用のpackage versionとcommit hashを取得する.

    Returns:
        tuple[str, str]: installed package versionとshort git HEAD hash. gitが利用できない
            場合のhashは`unknown`.

    Raises:
        importlib.metadata.PackageNotFoundError: Athena package metadataが実行環境で
            見つからない場合.
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


async def check_infrastructure(container: AsyncContainer) -> None:
    """PostgreSQLとValkeyへの接続を確認する.

    Args:
        container (AsyncContainer): database engineとValkey clientを解決するDishka container.

    Returns:
        None: PostgreSQLの`SELECT 1`とValkeyの`ping`を完了し, 呼び出し側へ値を返さずに
            終了する.
    """
    engine = await container.get(AsyncEngine)
    async with engine.connect() as conn:
        _ = await conn.execute(text("SELECT 1"))
    logger.info("startup_health_check", service="postgresql", status="ok")

    valkey = await container.get(GlideClient)
    _ = await valkey.ping()
    logger.info("startup_health_check", service="valkey", status="ok")


async def health_endpoint(request: Request) -> PlainTextResponse:
    """versionとcommit hashを含むplain-text health responseを返す.

    Args:
        request (Request): `version_info`を保持するStarlette request.

    Returns:
        PlainTextResponse: `athena v<version> (<commit>)`形式のresponse.

    Notes:
        application lifespanが`request.app.state.version_info`を設定済みであることを前提とする.
    """
    version, commit = request.app.state.version_info  # pyright: ignore[reportAny]
    return PlainTextResponse(f"athena v{version} ({commit})\n")


async def health_check_endpoint(request: Request) -> JSONResponse:
    """databaseとValkeyの状態を含むJSON health responseを返す.

    Args:
        request (Request): `version_info`と`dishka_container`を保持するStarlette request.

    Returns:
        JSONResponse: 両serviceが正常なら200/healthy,いずれかが失敗なら503/unhealthyの
            response.

    Notes:
        application lifespanがrequest app stateを設定済みであることを前提とし,各serviceの
        確認失敗はresponseの`checks`へ`error`として記録する.
    """
    version, commit = request.app.state.version_info  # pyright: ignore[reportAny]
    container: AsyncContainer = request.app.state.dishka_container  # pyright: ignore[reportAny]

    checks: dict[str, str] = {}

    try:
        engine = await container.get(AsyncEngine)
        async with engine.connect() as conn:
            _ = await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error"

    try:
        valkey = await container.get(GlideClient)
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

"""公開ASGIエントリーポイントを提供する.

`uvicorn osu_server.app:app`から参照されるruntime objectを公開し,
ルーティング,middleware,依存graphの構築はcomposition packageに委譲する.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.composition.application import create_app
from osu_server.composition.health import (
    get_version_info,
    health_check_endpoint,
    health_endpoint,
)
from osu_server.composition.middleware import RequestLoggingMiddleware

if TYPE_CHECKING:
    from starlette.applications import Starlette

__all__ = [
    "RequestLoggingMiddleware",
    "app",
    "create_app",
    "get_version_info",
    "health_check_endpoint",
    "health_endpoint",
]

app: Starlette = create_app()

"""公開 ASGI エントリポイントと互換 facade。

``uvicorn osu_server.app:app`` の外部契約はこの module に残し、
実装の組み立ては ``osu_server.composition`` に閉じ込める。
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

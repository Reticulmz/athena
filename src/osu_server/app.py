"""Public ASGI entrypoint and compatibility facade.

The ``uvicorn osu_server.app:app`` contract is intentionally kept here while
implementation details live in ``osu_server.composition``.
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
from osu_server.composition.service_registry import register_services

if TYPE_CHECKING:
    from starlette.applications import Starlette

__all__ = [
    "RequestLoggingMiddleware",
    "app",
    "create_app",
    "get_version_info",
    "health_check_endpoint",
    "health_endpoint",
    "register_services",
]

app: Starlette = create_app()

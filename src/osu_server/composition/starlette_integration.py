"""Starlette integration helpers for the Dishka app container."""

from __future__ import annotations

from starlette.middleware import Middleware
from starlette_dishka import ContainerMiddleware


def dishka_middleware() -> Middleware:
    """Return the Starlette middleware that opens Dishka request scopes."""
    return Middleware(ContainerMiddleware)

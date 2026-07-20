"""Dishka application containerをStarletteへ統合するhelperを提供する."""

from __future__ import annotations

from starlette.middleware import Middleware
from starlette_dishka import ContainerMiddleware


def dishka_middleware() -> Middleware:
    """Dishka request scopeを開くStarlette middlewareを生成する.

    Returns:
        Middleware: `ContainerMiddleware`を登録するためのStarlette middleware定義.
    """
    return Middleware(ContainerMiddleware)

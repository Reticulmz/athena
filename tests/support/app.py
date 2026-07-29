"""in-memory application composition用のtest supportを提供する."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from osu_server.app import create_app
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.applications import Starlette


def create_in_memory_app(
    *,
    blob_root: str | Path = ".data/test-blobs",
    packet_queue_max_size: int = 4096,
) -> Starlette:
    """in-memory provider overrideを持つASGI applicationを作成する.

    Args:
        blob_root (str | Path): test用blob storageを置くroot path.
        packet_queue_max_size (int): in-memory packet queueへ保存できる最大packet数.

    Returns:
        Starlette: testがdependency override付きで起動できるapplication.
    """
    return create_app(
        provider_overrides=(
            make_in_memory_runtime_provider_set(
                blob_root=blob_root,
                packet_queue_max_size=packet_queue_max_size,
            ),
        )
    )


async def resolve_dependency[T](app: Starlette, dependency_type: type[T]) -> T:
    """applicationのDishka containerから登録済みdependencyを解決する.

    Args:
        app (Starlette): in-memory provider override付きのapplication.
        dependency_type (type[T]): 解決するdependencyのruntime type.

    Returns:
        T: application containerが提供するdependency instance.

    Notes:
        dependency_typeはapplicationのcontainerへ登録済みでなければならない.
    """
    return await app.state.dishka_container.get(dependency_type)  # pyright: ignore[reportAny]


def resolve_dependency_sync[T](app: Starlette, dependency_type: type[T]) -> T:
    """同期TestClient testから登録済みdependencyを解決する.

    Args:
        app (Starlette): in-memory provider override付きのapplication.
        dependency_type (type[T]): 解決するdependencyのruntime type.

    Returns:
        T: application containerが提供するdependency instance.

    Notes:
        実行中のevent loopを持たない同期testからだけ利用する.
    """
    return asyncio.run(resolve_dependency(app, dependency_type))

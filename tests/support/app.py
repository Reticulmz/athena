"""Test helpers for app composition."""

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
    """Create the app with explicit in-memory provider overrides."""
    return create_app(
        provider_overrides=(
            make_in_memory_runtime_provider_set(
                blob_root=blob_root,
                packet_queue_max_size=packet_queue_max_size,
            ),
        )
    )


async def resolve_dependency[T](app: Starlette, dependency_type: type[T]) -> T:
    """Resolve a dependency from the app's Dishka container."""
    return await app.state.dishka_container.get(dependency_type)  # pyright: ignore[reportAny]


def resolve_dependency_sync[T](app: Starlette, dependency_type: type[T]) -> T:
    """Resolve a dependency from sync TestClient tests."""
    return asyncio.run(resolve_dependency(app, dependency_type))

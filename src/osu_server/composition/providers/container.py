"""Container factories for app and worker composition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dishka import make_async_container

from osu_server.composition.providers.app import AppProviderSet
from osu_server.composition.providers.common import CommonProviderSet
from osu_server.composition.providers.worker import WorkerProviderSet

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dishka import AsyncContainer, Provider

    from osu_server.config import AppConfig


def make_app_container(
    config: AppConfig,
    overrides: Iterable[Provider] = (),
) -> AsyncContainer:
    """Build the app dependency graph with explicit provider overrides."""
    return make_async_container(
        CommonProviderSet(config),
        AppProviderSet(),
        *overrides,
    )


def make_worker_container(
    config: AppConfig,
    overrides: Iterable[Provider] = (),
) -> AsyncContainer:
    """Build the worker dependency graph with explicit provider overrides."""
    return make_async_container(
        CommonProviderSet(config),
        WorkerProviderSet(),
        *overrides,
    )

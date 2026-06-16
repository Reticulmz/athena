"""CLI-adjacent composition for PP recalculation commands."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from dishka import make_async_container

from osu_server.composition.providers.infrastructure import InfrastructureProviderSet
from osu_server.composition.providers.performance_cli import PerformanceCliProviderSet
from osu_server.composition.providers.repositories import RepositoryProviderSet
from osu_server.services.commands.scores.performance import (
    CreatePerformanceRecalculationBatchUseCase,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable

    from dishka import AsyncContainer, Provider

    from osu_server.config import AppConfig


def make_performance_cli_container(
    config: AppConfig,
    overrides: Iterable[Provider] = (),
) -> AsyncContainer:
    """Build the CLI graph for PP recalculation without calculator runtime imports."""
    return make_async_container(
        InfrastructureProviderSet(config),
        RepositoryProviderSet(),
        PerformanceCliProviderSet(),
        *overrides,
    )


@asynccontextmanager
async def create_performance_recalculation_batch_use_case(
    config: AppConfig,
) -> AsyncGenerator[CreatePerformanceRecalculationBatchUseCase]:
    """Resolve the production PP recalculation use-case without calculator imports."""
    container = make_performance_cli_container(config)
    try:
        yield await container.get(CreatePerformanceRecalculationBatchUseCase)
    finally:
        await container.close()


__all__ = (
    "create_performance_recalculation_batch_use_case",
    "make_performance_cli_container",
)

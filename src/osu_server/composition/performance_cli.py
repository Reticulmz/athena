"""PP recalculation command用のCLI隣接dependency compositionを提供する.

performance calculator runtimeを含めず,recalculation batch作成に必要なproviderだけを組み立てる.
"""

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
    """PP recalculation CLI用のDishka containerを構築する.

    Args:
        config (AppConfig): infrastructure providerが使用するruntime設定.
        overrides (Iterable[Provider]): production provider setへ追加するDishka provider.

    Returns:
        AsyncContainer: recalculation batch作成に必要なdependencyを解決するcontainer.

    Notes:
        calculator runtime providerはこのcontainerへ登録しない.
    """
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
    """productionのperformance recalculation batch use-caseを一時的に解決する.

    Args:
        config (AppConfig): 一時containerのinfrastructure設定.

    Yields:
        CreatePerformanceRecalculationBatchUseCase: callerがbatchを作成するためのuse-case.

    Notes:
        yield終了後は一時containerを必ずcloseする.
    """
    container = make_performance_cli_container(config)
    try:
        yield await container.get(CreatePerformanceRecalculationBatchUseCase)
    finally:
        await container.close()


__all__ = (
    "create_performance_recalculation_batch_use_case",
    "make_performance_cli_container",
)

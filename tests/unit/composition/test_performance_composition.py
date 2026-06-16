"""Composition tests for performance subsystem defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.factories.config import make_app_config

from osu_server.composition.providers.container import make_app_container, make_worker_container
from osu_server.composition.providers.test import (
    TestProviderSet,
    make_in_memory_runtime_provider_set,
    replace_value,
)
from osu_server.domain.scores.performance import FormulaProfilePolicy
from osu_server.domain.scores.score import Playstyle
from osu_server.infrastructure.performance.interfaces import PerformanceCalculator
from osu_server.infrastructure.performance.rosu_calculator import RosuPerformanceCalculator
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignal,
)
from osu_server.infrastructure.state.memory.performance_completion_signal import (
    InMemoryPerformanceCompletionSignal,
)
from osu_server.infrastructure.state.valkey.performance_completion_signal import (
    ValkeyPerformanceCompletionPublisher,
    ValkeyPerformanceCompletionSignal,
)
from osu_server.jobs.score_performance import TaskiqPerformanceCalculationWorkerWake
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceQueryRepository,
)
from osu_server.repositories.memory.queries.score_performance import (
    InMemoryScorePerformanceQueryRepository,
)
from osu_server.services.commands.scores.performance import (
    BeatmapMirrorPerformanceBeatmapFileProvider,
    ExecutePerformanceCalculationUseCase,
    PerformanceBeatmapFileProvider,
    PerformanceCalculationWorkerWake,
    PerformanceRuntimeSettings,
    RequestPerformanceCalculationUseCase,
)
from osu_server.services.queries.scores import PerformanceResponseQuery

if TYPE_CHECKING:
    from pathlib import Path


class _FakePerformanceCompletionPublisher:
    async def publish(self, message: str, channel: str) -> int:
        _ = message
        _ = channel
        return 0


@pytest.mark.asyncio
async def test_app_container_resolves_performance_defaults(tmp_path: Path) -> None:
    config = make_app_config(environment="test", blob_storage_local_root=str(tmp_path / "blobs"))
    container = make_app_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    try:
        settings = await container.get(PerformanceRuntimeSettings)
        policy = await container.get(FormulaProfilePolicy)
        beatmap_file_provider = await container.get(PerformanceBeatmapFileProvider)
        calculator = await container.get(PerformanceCalculator)
        completion_signal = await container.get(PerformanceCompletionSignal)
        query_repository = await container.get(ScorePerformanceQueryRepository)
        worker_wake = await container.get(PerformanceCalculationWorkerWake)
        request_use_case = await container.get(RequestPerformanceCalculationUseCase)
        execute_use_case = await container.get(ExecutePerformanceCalculationUseCase)
        response_query = await container.get(PerformanceResponseQuery)

        assert settings.worker_chunk_size == 100
        assert policy.active_profile_for(Playstyle.VANILLA) is settings.active_formula_profile_for(
            Playstyle.VANILLA
        )
        assert isinstance(beatmap_file_provider, BeatmapMirrorPerformanceBeatmapFileProvider)
        assert isinstance(calculator, RosuPerformanceCalculator)
        assert isinstance(completion_signal, InMemoryPerformanceCompletionSignal)
        assert isinstance(query_repository, InMemoryScorePerformanceQueryRepository)
        assert isinstance(worker_wake, TaskiqPerformanceCalculationWorkerWake)
        assert isinstance(request_use_case, RequestPerformanceCalculationUseCase)
        assert isinstance(execute_use_case, ExecutePerformanceCalculationUseCase)
        assert isinstance(response_query, PerformanceResponseQuery)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_app_container_resolves_valkey_completion_signal_by_default() -> None:
    config = make_app_config(environment="development")
    container = make_app_container(
        config,
        overrides=(
            TestProviderSet(
                replace_value(
                    ValkeyPerformanceCompletionPublisher,
                    _FakePerformanceCompletionPublisher(),
                ),
            ),
        ),
    )

    try:
        completion_signal = await container.get(PerformanceCompletionSignal)

        assert isinstance(completion_signal, ValkeyPerformanceCompletionSignal)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_worker_container_resolves_performance_defaults(tmp_path: Path) -> None:
    config = make_app_config(environment="test", blob_storage_local_root=str(tmp_path / "blobs"))
    container = make_worker_container(
        config,
        overrides=(make_in_memory_runtime_provider_set(blob_root=tmp_path / "blobs"),),
    )

    try:
        settings = await container.get(PerformanceRuntimeSettings)
        policy = await container.get(FormulaProfilePolicy)
        beatmap_file_provider = await container.get(PerformanceBeatmapFileProvider)
        calculator = await container.get(PerformanceCalculator)
        completion_signal = await container.get(PerformanceCompletionSignal)
        request_use_case = await container.get(RequestPerformanceCalculationUseCase)
        execute_use_case = await container.get(ExecutePerformanceCalculationUseCase)

        assert settings.claim_timeout.total_seconds() == 300
        assert policy.active_profile_for(Playstyle.VANILLA) is settings.active_formula_profile_for(
            Playstyle.VANILLA
        )
        assert isinstance(beatmap_file_provider, BeatmapMirrorPerformanceBeatmapFileProvider)
        assert isinstance(calculator, RosuPerformanceCalculator)
        assert isinstance(completion_signal, InMemoryPerformanceCompletionSignal)
        assert isinstance(request_use_case, RequestPerformanceCalculationUseCase)
        assert isinstance(execute_use_case, ExecutePerformanceCalculationUseCase)
    finally:
        await container.close()

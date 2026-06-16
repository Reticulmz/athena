"""Composition tests for performance subsystem defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.factories.config import make_app_config

from osu_server.composition.providers.container import make_app_container, make_worker_container
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.domain.scores.performance import FormulaProfilePolicy
from osu_server.domain.scores.score import Playstyle
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceQueryRepository,
)
from osu_server.repositories.memory.queries.score_performance import (
    InMemoryScorePerformanceQueryRepository,
)
from osu_server.services.commands.scores.performance import PerformanceRuntimeSettings

if TYPE_CHECKING:
    from pathlib import Path


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
        query_repository = await container.get(ScorePerformanceQueryRepository)

        assert settings.worker_chunk_size == 100
        assert policy.active_profile_for(Playstyle.VANILLA) is settings.active_formula_profile_for(
            Playstyle.VANILLA
        )
        assert isinstance(query_repository, InMemoryScorePerformanceQueryRepository)
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

        assert settings.claim_timeout.total_seconds() == 300
        assert policy.active_profile_for(Playstyle.VANILLA) is settings.active_formula_profile_for(
            Playstyle.VANILLA
        )
    finally:
        await container.close()

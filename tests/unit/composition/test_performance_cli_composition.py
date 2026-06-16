"""Composition tests for the PP recalculation CLI graph."""

from __future__ import annotations

import pytest
from tests.factories.config import make_app_config

from osu_server.composition.performance_cli import make_performance_cli_container
from osu_server.infrastructure.performance.calculator_identity import (
    InstalledPackagePerformanceCalculatorIdentity,
)
from osu_server.services.commands.scores.performance import (
    CreatePerformanceRecalculationBatchUseCase,
    PerformanceCalculatorIdentity,
)


@pytest.mark.asyncio
async def test_performance_cli_container_resolves_recalculation_use_case() -> None:
    container = make_performance_cli_container(make_app_config(environment="test"))

    try:
        use_case = await container.get(CreatePerformanceRecalculationBatchUseCase)
        identity = await container.get(PerformanceCalculatorIdentity)

        assert isinstance(use_case, CreatePerformanceRecalculationBatchUseCase)
        assert isinstance(identity, InstalledPackagePerformanceCalculatorIdentity)
        assert identity.calculator_name() == "rosu-pp-py"
    finally:
        await container.close()

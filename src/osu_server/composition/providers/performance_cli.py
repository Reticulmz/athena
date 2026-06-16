"""CLI-adjacent providers for PP recalculation commands."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.domain.scores.performance import FormulaProfilePolicy
from osu_server.infrastructure.performance.calculator_identity import (
    InstalledPackagePerformanceCalculatorIdentity,
)
from osu_server.jobs.score_performance import TaskiqPerformanceRecalculationBatchWorkerWake
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceQueryRepository,
)
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.scores.performance import (
    CreatePerformanceRecalculationBatchUseCase,
    PerformanceCalculatorIdentity,
    PerformanceRecalculationBatchWorkerWake,
    PerformanceRuntimeSettings,
)

_DISHKA_RUNTIME_HINTS = (
    AsyncBroker,
    CreatePerformanceRecalculationBatchUseCase,
    FormulaProfilePolicy,
    InstalledPackagePerformanceCalculatorIdentity,
    PerformanceCalculatorIdentity,
    PerformanceRecalculationBatchWorkerWake,
    PerformanceRuntimeSettings,
    ScorePerformanceQueryRepository,
    UnitOfWorkFactory,
)


@final
class PerformanceCliProviderSet(Provider):
    """Providers for the PP recalculation CLI boundary."""

    scope = Scope.APP

    @provide
    def performance_runtime_settings(self) -> PerformanceRuntimeSettings:
        return PerformanceRuntimeSettings()

    @provide
    def formula_profile_policy(
        self,
        settings: PerformanceRuntimeSettings,
    ) -> FormulaProfilePolicy:
        return FormulaProfilePolicy(settings.formula_profiles_by_playstyle)

    @provide
    def performance_calculator_identity(self) -> PerformanceCalculatorIdentity:
        return InstalledPackagePerformanceCalculatorIdentity()

    @provide
    def performance_recalculation_batch_worker_wake(
        self,
        broker: AsyncBroker,
    ) -> PerformanceRecalculationBatchWorkerWake:
        return TaskiqPerformanceRecalculationBatchWorkerWake(broker)

    @provide
    def create_performance_recalculation_batch_use_case(
        self,
        repository: ScorePerformanceQueryRepository,
        unit_of_work_factory: UnitOfWorkFactory,
        calculator_identity: PerformanceCalculatorIdentity,
        worker_wake: PerformanceRecalculationBatchWorkerWake,
        formula_profile_policy: FormulaProfilePolicy,
    ) -> CreatePerformanceRecalculationBatchUseCase:
        return CreatePerformanceRecalculationBatchUseCase(
            query_repository=repository,
            unit_of_work_factory=unit_of_work_factory,
            calculator_identity=calculator_identity,
            worker_wake=worker_wake,
            formula_profile_policy=formula_profile_policy,
        )


__all__ = ("PerformanceCliProviderSet",)

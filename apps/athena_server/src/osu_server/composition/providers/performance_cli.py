"""PP recalculation CLI専用のperformance providerを定義する.

このmoduleはapp/worker graphのcalculator実装と分離し, installed packageのidentityを
batch作成commandへ渡すCLI compositionを所有する.
"""

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
    """PP recalculation CLI boundaryの依存を提供する.

    Attributes:
        scope (Scope): CLI containerの生存期間と一致するDishka scope.
    """

    scope = Scope.APP

    @provide
    def performance_runtime_settings(self) -> PerformanceRuntimeSettings:
        """CLI batch作成に使うdefault performance runtime設定を提供する.

        Returns:
            PerformanceRuntimeSettings: formula profileとbatch制約のdefault設定.
        """
        return PerformanceRuntimeSettings()

    @provide
    def formula_profile_policy(
        self,
        settings: PerformanceRuntimeSettings,
    ) -> FormulaProfilePolicy:
        """CLIで選択するplaystyle別formula profile policyを提供する.

        Args:
            settings (PerformanceRuntimeSettings): playstyle別formula profile設定を持つruntime値.

        Returns:
            FormulaProfilePolicy: recalculation batchに適用するformula profileを選ぶpolicy.
        """
        return FormulaProfilePolicy(settings.formula_profiles_by_playstyle)

    @provide
    def performance_calculator_identity(self) -> PerformanceCalculatorIdentity:
        """Installed rosu-pp-py packageを表すcalculator identityを提供する.

        Returns:
            PerformanceCalculatorIdentity: batch metadataへrecordするinstalled calculator identity.
        """
        return InstalledPackagePerformanceCalculatorIdentity()

    @provide
    def performance_recalculation_batch_worker_wake(
        self,
        broker: AsyncBroker,
    ) -> PerformanceRecalculationBatchWorkerWake:
        """CLI作成batchをworkerへenqueueするwake adapterを提供する.

        Args:
            broker (AsyncBroker): performance recalculation jobが登録済みのTaskiq broker.

        Returns:
            PerformanceRecalculationBatchWorkerWake: batch processing jobを起動するport実装.
        """
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
        """CLIからrecalculation batchを作るcommand use caseを提供する.

        Args:
            repository (ScorePerformanceQueryRepository): recalculation対象scoreを読むquery
                repository.
            unit_of_work_factory (UnitOfWorkFactory): batchとscore stateを更新する
                transaction factory.
            calculator_identity (PerformanceCalculatorIdentity): batch metadataへrecordする
                calculator identity.
            worker_wake (PerformanceRecalculationBatchWorkerWake): batch workerをenqueueするport.
            formula_profile_policy (FormulaProfilePolicy): batchに適用するformula profileを
                選ぶpolicy.

        Returns:
            CreatePerformanceRecalculationBatchUseCase: CLI commandが実行するbatch作成use case.
        """
        return CreatePerformanceRecalculationBatchUseCase(
            query_repository=repository,
            unit_of_work_factory=unit_of_work_factory,
            calculator_identity=calculator_identity,
            worker_wake=worker_wake,
            formula_profile_policy=formula_profile_policy,
        )


__all__ = ("PerformanceCliProviderSet",)

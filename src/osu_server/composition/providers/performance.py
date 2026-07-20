"""app/worker graphで共有するscore performance providerを定義する.

このmoduleはPP calculation, completion signal, beatmap file解決, worker wakeを
performance command/query use caseへ配線する.
"""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope
from glide import GlideClient
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.composition.providers.beatmaps_app import enqueue_beatmap_fetch
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import BeatmapFetchTarget, BeatmapFreshnessPolicy
from osu_server.domain.scores.performance import FormulaProfilePolicy
from osu_server.infrastructure.cache.valkey_client import (
    ValkeyPubSubCallback,
    create_valkey_pubsub_client,
)
from osu_server.infrastructure.performance.interfaces import PerformanceCalculator
from osu_server.infrastructure.performance.rosu_calculator import RosuPerformanceCalculator
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignal,
)
from osu_server.infrastructure.state.valkey.performance_completion_signal import (
    ValkeyPerformanceCompletionPublisher,
    ValkeyPerformanceCompletionSignal,
)
from osu_server.jobs.score_performance import (
    TaskiqPerformanceCalculationWorkerWake,
    TaskiqPerformanceRecalculationBatchWorkerWake,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.score_performance import (
    ScorePerformanceQueryRepository,
)
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.scores.performance import (
    BeatmapMirrorPerformanceBeatmapFileProvider,
    CreatePerformanceRecalculationBatchUseCase,
    ExecutePerformanceCalculationUseCase,
    PerformanceBeatmapFileProvider,
    PerformanceCalculationWorkerWake,
    PerformanceRecalculationBatchWorkerWake,
    PerformanceRuntimeSettings,
    ProcessPerformanceRecalculationBatchUseCase,
    RequestPerformanceCalculationUseCase,
)
from osu_server.services.commands.storage import BlobStorageService
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)
from osu_server.services.queries.scores import PerformanceResponseQuery

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    AsyncBroker,
    BeatmapEligibilityService,
    BeatmapFetchTarget,
    BeatmapFreshnessPolicy,
    BeatmapMirrorService,
    BeatmapQueryRepository,
    BlobStorageService,
    FormulaProfilePolicy,
    GlideClient,
    PerformanceBeatmapFileProvider,
    PerformanceCalculationWorkerWake,
    PerformanceCalculator,
    PerformanceCompletionSignal,
    PerformanceRecalculationBatchWorkerWake,
    PerformanceResponseQuery,
    PerformanceRuntimeSettings,
    CreatePerformanceRecalculationBatchUseCase,
    ProcessPerformanceRecalculationBatchUseCase,
    RequestPerformanceCalculationUseCase,
    ExecutePerformanceCalculationUseCase,
    ScorePerformanceQueryRepository,
    TaskiqPerformanceCalculationWorkerWake,
    TaskiqPerformanceRecalculationBatchWorkerWake,
    UnitOfWorkFactory,
    ValkeyPerformanceCompletionPublisher,
)


@final
class PerformanceProviderSet(Provider):
    """score performanceのruntime設定, policy, use caseを提供する.

    Attributes:
        scope (Scope): app/worker processの生存期間と一致するDishka scope.
    """

    scope = Scope.APP

    @provide
    def performance_runtime_settings(self) -> PerformanceRuntimeSettings:
        """Performance subsystemのdefault runtime設定を提供する.

        Returns:
            PerformanceRuntimeSettings: worker batch, claim timeout, formula profileのdefault設定.
        """
        return PerformanceRuntimeSettings()

    @provide
    def formula_profile_policy(
        self,
        settings: PerformanceRuntimeSettings,
    ) -> FormulaProfilePolicy:
        """playstyle別formula profile選択policyを提供する.

        Args:
            settings (PerformanceRuntimeSettings): playstyle別formula profile設定を持つruntime値.

        Returns:
            FormulaProfilePolicy: score calculationでactive formula profileを選ぶpolicy.
        """
        return FormulaProfilePolicy(settings.formula_profiles_by_playstyle)

    @provide
    def performance_calculator(self) -> PerformanceCalculator:
        """rosu-pp-pyを使うperformance calculatorを提供する.

        Returns:
            PerformanceCalculator: osu! scoreからperformance値を計算するproduction adapter.
        """
        return RosuPerformanceCalculator()

    @provide
    def performance_calculation_worker_wake(
        self,
        broker: AsyncBroker,
    ) -> PerformanceCalculationWorkerWake:
        """単一score calculation jobをenqueueするworker wake adapterを提供する.

        Args:
            broker (AsyncBroker): score performance jobが登録済みのTaskiq broker.

        Returns:
            PerformanceCalculationWorkerWake: calculation request後にworkerを起動するport実装.
        """
        return TaskiqPerformanceCalculationWorkerWake(broker)

    @provide
    def performance_recalculation_batch_worker_wake(
        self,
        broker: AsyncBroker,
    ) -> PerformanceRecalculationBatchWorkerWake:
        """Performance recalculation batch jobをenqueueするworker wake adapterを提供する.

        Args:
            broker (AsyncBroker): score performance jobが登録済みのTaskiq broker.

        Returns:
            PerformanceRecalculationBatchWorkerWake: batch作成後にworkerを起動するport実装.
        """
        return TaskiqPerformanceRecalculationBatchWorkerWake(broker)

    @provide
    def request_performance_calculation_use_case(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        worker_wake: PerformanceCalculationWorkerWake,
        formula_profile_policy: FormulaProfilePolicy,
    ) -> RequestPerformanceCalculationUseCase:
        """scoreごとのperformance calculation request use caseを提供する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): calculation requestを永続化する
                transaction factory.
            worker_wake (PerformanceCalculationWorkerWake): calculation workerをenqueueするport.
            formula_profile_policy (FormulaProfilePolicy): requestに適用するformula profileを
                選ぶpolicy.

        Returns:
            RequestPerformanceCalculationUseCase: performance calculationを要求するcommand
                use case.
        """
        return RequestPerformanceCalculationUseCase(
            unit_of_work_factory=unit_of_work_factory,
            worker_wake=worker_wake,
            formula_profile_policy=formula_profile_policy,
        )

    @provide
    def create_performance_recalculation_batch_use_case(
        self,
        repository: ScorePerformanceQueryRepository,
        unit_of_work_factory: UnitOfWorkFactory,
        calculator: PerformanceCalculator,
        worker_wake: PerformanceRecalculationBatchWorkerWake,
        formula_profile_policy: FormulaProfilePolicy,
    ) -> CreatePerformanceRecalculationBatchUseCase:
        """Recalculation batch作成command use caseを提供する.

        Args:
            repository (ScorePerformanceQueryRepository): recalculation対象scoreを読むquery
                repository.
            unit_of_work_factory (UnitOfWorkFactory): batchとscore stateを更新する
                transaction factory.
            calculator (PerformanceCalculator): installed calculatorのidentityを報告するadapter.
            worker_wake (PerformanceRecalculationBatchWorkerWake): batch workerをenqueueするport.
            formula_profile_policy (FormulaProfilePolicy): batchに適用するformula profileを
                選ぶpolicy.

        Returns:
            CreatePerformanceRecalculationBatchUseCase: recalculation batchを永続化して
                enqueueするuse case.
        """
        return CreatePerformanceRecalculationBatchUseCase(
            query_repository=repository,
            unit_of_work_factory=unit_of_work_factory,
            calculator_identity=calculator,
            worker_wake=worker_wake,
            formula_profile_policy=formula_profile_policy,
        )

    @provide
    def process_performance_recalculation_batch_use_case(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        request_use_case: RequestPerformanceCalculationUseCase,
        calculator: PerformanceCalculator,
        settings: PerformanceRuntimeSettings,
    ) -> ProcessPerformanceRecalculationBatchUseCase:
        """Recalculation batchをchunkへ展開するworker use caseを提供する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): batch claimと進捗更新を行う
                transaction factory.
            request_use_case (RequestPerformanceCalculationUseCase): individual calculationを
                要求するuse case.
            calculator (PerformanceCalculator): installed calculatorのidentityを報告するadapter.
            settings (PerformanceRuntimeSettings): worker chunkとclaim timeoutを持つruntime設定.

        Returns:
            ProcessPerformanceRecalculationBatchUseCase: claimed batchをcalculation requestへ
                展開するuse case.
        """
        return ProcessPerformanceRecalculationBatchUseCase(
            unit_of_work_factory=unit_of_work_factory,
            request_use_case=request_use_case,
            calculator_identity=calculator,
            settings=settings,
        )

    @provide
    def execute_performance_calculation_use_case(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        beatmap_file_provider: PerformanceBeatmapFileProvider,
        calculator: PerformanceCalculator,
        completion_signal: PerformanceCompletionSignal,
        settings: PerformanceRuntimeSettings,
    ) -> ExecutePerformanceCalculationUseCase:
        """Queued performance calculationを実行するworker use caseを提供する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): calculation outcomeを永続化する
                transaction factory.
            beatmap_file_provider (PerformanceBeatmapFileProvider): calculation対象のbeatmap
                fileを解決するport.
            calculator (PerformanceCalculator): performance値を計算するproduction adapter.
            completion_signal (PerformanceCompletionSignal): calculation完了を待機者へ通知するport.
            settings (PerformanceRuntimeSettings): calculation実行制約を持つruntime設定.

        Returns:
            ExecutePerformanceCalculationUseCase: worker jobからcalculationを実行するuse case.
        """
        return ExecutePerformanceCalculationUseCase(
            unit_of_work_factory=unit_of_work_factory,
            beatmap_file_provider=beatmap_file_provider,
            calculator=calculator,
            completion_signal=completion_signal,
            settings=settings,
        )

    @provide
    def performance_response_query(
        self,
        repository: ScorePerformanceQueryRepository,
        completion_signal: PerformanceCompletionSignal,
        settings: PerformanceRuntimeSettings,
    ) -> PerformanceResponseQuery:
        """performance結果をbounded wait付きで読むqueryを提供する.

        Args:
            repository (ScorePerformanceQueryRepository): persisted performance resultを読む
                query repository.
            completion_signal (PerformanceCompletionSignal): in-flight calculation完了を待つ
                signal port.
            settings (PerformanceRuntimeSettings): queryが待機できるbounded timeoutを持つ
                runtime設定.

        Returns:
            PerformanceResponseQuery: score performance responseを返すread query.
        """
        return PerformanceResponseQuery(
            repository=repository,
            completion_signal=completion_signal,
            bounded_wait=settings.bounded_wait,
        )

    @provide
    def performance_beatmap_file_provider(
        self,
        repository: BeatmapQueryRepository,
        eligibility_service: BeatmapEligibilityService,
        freshness_policy: BeatmapFreshnessPolicy,
        broker: AsyncBroker,
        config: AppConfig,
        blob_storage: BlobStorageService,
    ) -> PerformanceBeatmapFileProvider:
        """Mirror policyを適用してperformance用beatmap fileを解決するproviderを提供する.

        Args:
            repository (BeatmapQueryRepository): beatmap metadataとfile locationを読むquery
                repository.
            eligibility_service (BeatmapEligibilityService): mirror fetchの許可を判定するservice.
            freshness_policy (BeatmapFreshnessPolicy): cached beatmapのfreshnessを判定するpolicy.
            broker (AsyncBroker): stale beatmap refresh jobが登録済みのTaskiq broker.
            config (AppConfig): mirror trustとofficial source利用可否を持つruntime設定.
            blob_storage (BlobStorageService): resolved blob contentを読むstorage service.

        Returns:
            PerformanceBeatmapFileProvider: mirror refreshをenqueueし, Ready/Pending/Unavailableの
                file解決結果を返すadapter.
        """
        beatmap_resolver = BeatmapMirrorService(
            repository=repository,
            eligibility_service=eligibility_service,
            freshness_policy=freshness_policy,
            mirror_trust_enabled=config.beatmap_mirror_trust_policy == "trusted",
            official_sources_available=config.beatmap_official_sources_enabled,
            enqueue_refresh=lambda target: enqueue_beatmap_fetch(broker, target),
        )
        return BeatmapMirrorPerformanceBeatmapFileProvider(
            beatmap_resolver=beatmap_resolver,
            blob_storage=blob_storage,
        )

    @provide
    def performance_completion_publisher(
        self,
        valkey: GlideClient,
    ) -> ValkeyPerformanceCompletionPublisher:
        """Completion event publish用にshared Valkey clientを提供する.

        Args:
            valkey (GlideClient): APP scopeで所有されるshared Valkey client.

        Returns:
            ValkeyPerformanceCompletionPublisher: completion signalがpublishに使用するclient alias.

        Notes:
            lifecycleはinfrastructure providerが所有するため, completion signalはclientを
                closeしない.
        """
        return valkey

    @provide
    def performance_completion_signal(
        self,
        publisher: ValkeyPerformanceCompletionPublisher,
        config: AppConfig,
    ) -> PerformanceCompletionSignal:
        """Valkey pub/subを使うperformance completion signalを提供する.

        Args:
            publisher (ValkeyPerformanceCompletionPublisher): completion eventをpublishする
                shared client.
            config (AppConfig): subscription client接続用Valkey URLを含むruntime設定.

        Returns:
            PerformanceCompletionSignal: calculation完了のpublishと待機を行うsignal adapter.
        """
        valkey_url = str(config.valkey_url)

        async def pubsub_client_factory(callback: ValkeyPubSubCallback) -> GlideClient:
            """Completion subscription用の専用Valkey clientを作る.

            Args:
                callback (ValkeyPubSubCallback): pub/sub messageをsignalへ渡すcallback.

            Returns:
                GlideClient: callbackを登録済みのsubscription専用client.

            Notes:
                ValkeyPerformanceCompletionSignal.wait()がfinally節でこのsubscription clientの
                    unsubscribe/closeを所有する.
            """
            return await create_valkey_pubsub_client(valkey_url, callback)

        return ValkeyPerformanceCompletionSignal(
            publisher,
            pubsub_client_factory=pubsub_client_factory,
        )

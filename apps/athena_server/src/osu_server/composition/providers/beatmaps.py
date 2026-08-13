"""appとworkerで共有するbeatmap providerを構成する."""

from __future__ import annotations

from collections import abc
from datetime import timedelta
from typing import final

from dishka import Provider, Scope
from meilisearch_python_sdk import AsyncClient as MeilisearchAsyncClient
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import (
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
)
from osu_server.infrastructure.beatmaps import (
    BeatmapFileProviderService,
    CompositeBeatmapMetadataProvider,
    MirrorMetadataProviderService,
    OsuApiMetadataProviderService,
)
from osu_server.infrastructure.http.beatmap_http_client import (
    BeatmapHttpClient as ConcreteBeatmapHttpClient,
)
from osu_server.jobs.osu_direct import TaskiqDirectExternalIndexUpdateWorkerWake
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
    RecordDirectSearchCoverageUseCase,
)
from osu_server.services.commands.storage.blob_storage import BlobStorageService
from osu_server.services.queries.beatmaps import (
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
)
from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
    DirectExternalIndexUpdateWorkerWake,
)

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
    BeatmapLeaderboardRebuildWorkerWake,
    DirectExternalIndexUpdateWorkerWake,
    BeatmapQueryRepository,
    BlobStorageService,
    RecordDirectSearchCoverageUseCase,
    abc.AsyncIterator,
    MeilisearchAsyncClient,
    TaskiqDirectExternalIndexUpdateWorkerWake,
    UnitOfWorkFactory,
    AsyncBroker,
)


@final
class BeatmapProviderSet(Provider):
    """共有beatmap policy,query,fetch workflowをAPP scopeで登録する.

    Attributes:
        scope (Scope): appとworker container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    async def meilisearch_direct_client(
        self,
        config: AppConfig,
    ) -> abc.AsyncIterator[MeilisearchAsyncClient | None]:
        """設定がある場合だけMeilisearch SDK clientをAPP scopeで提供する.

        Args:
            config (AppConfig): Meilisearch URLとaccess keyを持つ設定.

        Yields:
            MeilisearchAsyncClient | None: URL未設定ならNone, 設定済みならclose管理付きclient.
        """
        if config.osu_direct_meilisearch_url is None:
            yield None
            return
        async with MeilisearchAsyncClient(
            config.osu_direct_meilisearch_url,
            config.osu_direct_meilisearch_access_key,
        ) as client:
            yield client

    @provide
    def beatmap_freshness_policy(self, config: AppConfig) -> BeatmapFreshnessPolicy:
        """設定された更新間隔からbeatmap freshness policyを構成する.

        Args:
            config (AppConfig): ranked,pending,graveyard,mirrorの更新秒数を持つ設定.

        Returns:
            BeatmapFreshnessPolicy: 各source種別の更新間隔を ``timedelta`` で表すpolicy.
        """
        return BeatmapFreshnessPolicy(
            ranked_refresh_interval=timedelta(
                seconds=config.beatmap_ranked_refresh_interval_seconds
            ),
            pending_refresh_interval=timedelta(
                seconds=config.beatmap_pending_refresh_interval_seconds
            ),
            graveyard_refresh_interval=timedelta(
                seconds=config.beatmap_graveyard_refresh_interval_seconds
            ),
            mirror_refresh_interval=timedelta(
                seconds=config.beatmap_mirror_refresh_interval_seconds
            ),
        )

    @provide
    def beatmap_metadata_provider(self, config: AppConfig) -> BeatmapMetadataProvider:
        """公式APIとcommunity mirrorを順に利用するmetadata providerを構成する.

        Args:
            config (AppConfig): 公式API credentialとmetadata mirror base URLを持つ設定.

        Returns:
            BeatmapMetadataProvider: 公式sourceとmirror sourceを組み合わせたprovider.

        Notes:
            未設定の公式credentialは空文字列として公式providerへ渡し,利用可否は上位workflowが判断する.
        """
        official = OsuApiMetadataProviderService(
            client_id=config.beatmap_official_api_client_id or "",
            client_secret=config.beatmap_official_api_client_secret or "",
            http_client=ConcreteBeatmapHttpClient(),
        )
        mirror = MirrorMetadataProviderService(
            http_client=ConcreteBeatmapHttpClient(),
            base_urls=config.beatmap_metadata_mirror_base_urls,
        )
        return CompositeBeatmapMetadataProvider(official=official, mirror=mirror)

    @provide
    def beatmap_file_provider(self, config: AppConfig) -> BeatmapFileProvider:
        """公式URLとcommunity mirrorを使うbeatmap file providerを構成する.

        Args:
            config (AppConfig): current/legacy osu URL templateとmirror URL templateを持つ設定.

        Returns:
            BeatmapFileProvider: 設定済みURL templateで ``.osu`` fileを取得するprovider.
        """
        return BeatmapFileProviderService(
            http_client=ConcreteBeatmapHttpClient(),
            osu_current_url_template=config.beatmap_osu_current_url_template,
            osu_legacy_url_template=config.beatmap_osu_legacy_url_template,
            mirror_url_templates=list(config.beatmap_community_mirror_url_templates),
        )

    @provide
    def beatmap_eligibility_service(self) -> BeatmapEligibilityService:
        """beatmapのmirror利用可否を判定するserviceを構成する.

        Returns:
            BeatmapEligibilityService: beatmap状態に基づく利用可否判定service.
        """
        return BeatmapEligibilityService()

    @provide
    def resolve_beatmap_by_id_query(
        self,
        repository: BeatmapQueryRepository,
    ) -> ResolveBeatmapByIdQuery:
        """Beatmap ID検索用queryをread repositoryと接続して構成する.

        Args:
            repository (BeatmapQueryRepository): beatmap read modelを取得するrepository.

        Returns:
            ResolveBeatmapByIdQuery: beatmap IDから既存metadataを解決するquery.
        """
        return ResolveBeatmapByIdQuery(repository)

    @provide
    def resolve_beatmap_by_checksum_query(
        self,
        repository: BeatmapQueryRepository,
    ) -> ResolveBeatmapByChecksumQuery:
        """checksum検索用queryをread repositoryと接続して構成する.

        Args:
            repository (BeatmapQueryRepository): beatmap read modelを取得するrepository.

        Returns:
            ResolveBeatmapByChecksumQuery: checksumから既存metadataを解決するquery.
        """
        return ResolveBeatmapByChecksumQuery(repository)

    @provide
    def fetch_beatmap_metadata_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
        metadata_provider: BeatmapMetadataProvider,
        freshness_policy: BeatmapFreshnessPolicy,
        config: AppConfig,
        leaderboard_rebuild_wake: BeatmapLeaderboardRebuildWorkerWake,
        direct_external_index_update_wake: DirectExternalIndexUpdateWorkerWake,
    ) -> FetchBeatmapMetadataUseCase:
        """Metadata fetch commandをsource policyとworker wake portで構成する.

        Args:
            uow_factory (UnitOfWorkFactory):
                metadata更新をtransactionで永続化するUnit of Work factory.
            metadata_provider (BeatmapMetadataProvider):
                公式sourceまたはmirrorからmetadataを取得するprovider.
            freshness_policy (BeatmapFreshnessPolicy): 取得済みmetadataの再取得要否を決めるpolicy.
            config (AppConfig): 公式sourceの利用可否を持つ実行時設定.
            leaderboard_rebuild_wake (BeatmapLeaderboardRebuildWorkerWake):
                metadata更新後にleaderboard rebuild workerを起動するport.
            direct_external_index_update_wake (DirectExternalIndexUpdateWorkerWake):
                metadata更新後にexternal index update workerを起動するport.

        Returns:
            FetchBeatmapMetadataUseCase: freshness判定,metadata永続化,rebuild wakeを行うcommand.
        """
        return FetchBeatmapMetadataUseCase(
            uow_factory=uow_factory,
            metadata_provider=metadata_provider,
            freshness_policy=freshness_policy,
            official_sources_available=config.beatmap_official_sources_enabled,
            leaderboard_rebuild_wake=leaderboard_rebuild_wake,
            direct_external_index_update_wake=direct_external_index_update_wake,
        )

    @provide
    def direct_external_index_update_worker_wake(
        self,
        broker: AsyncBroker,
    ) -> DirectExternalIndexUpdateWorkerWake:
        """External index update workerを起動するTaskiq portを構成する.

        Args:
            broker (AsyncBroker): external index update taskをenqueueするTaskiq broker.

        Returns:
            DirectExternalIndexUpdateWorkerWake: beatmapset単位のindex updateをworkerへ
            要求するport.
        """
        return TaskiqDirectExternalIndexUpdateWorkerWake(broker)

    @provide
    def record_direct_search_coverage_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> RecordDirectSearchCoverageUseCase:
        """検索時に観測したdirect coverage保存commandを構成する.

        Args:
            uow_factory (UnitOfWorkFactory): coverage recordを保存するcommand UoW factory.

        Returns:
            RecordDirectSearchCoverageUseCase: Stable handlerから呼ぶcoverage保存command.
        """
        return RecordDirectSearchCoverageUseCase(uow_factory)

    @provide
    def fetch_beatmap_file_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
        file_provider: BeatmapFileProvider,
        blob_storage: BlobStorageService,
    ) -> FetchBeatmapFileUseCase:
        """Beatmap file fetch commandを取得providerとblob storageで構成する.

        Args:
            uow_factory (UnitOfWorkFactory):
                file metadata更新をtransactionで永続化するUnit of Work factory.
            file_provider (BeatmapFileProvider): 外部sourceから ``.osu`` fileを取得するprovider.
            blob_storage (BlobStorageService): 取得したfile blobとmetadataを保存するservice.

        Returns:
            FetchBeatmapFileUseCase: beatmap fileを取得してblob storageへ保存するcommand.
        """
        return FetchBeatmapFileUseCase(
            uow_factory=uow_factory,
            file_provider=file_provider,
            blob_storage=blob_storage,
        )

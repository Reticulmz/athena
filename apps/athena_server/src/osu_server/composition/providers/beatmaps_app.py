"""app processから利用するbeatmap mirror providerを構成する."""

from __future__ import annotations

from typing import cast, final

import structlog
from dishka import Provider, Scope
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import (
    BeatmapFetchTarget,
    BeatmapFreshnessPolicy,
    DirectSearchBackend,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.sqlalchemy.queries.direct_search import ParadeDBSearchBackend
from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
from osu_server.services.queries.beatmaps import DirectPointLookupQuery, DirectSearchQuery
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    AsyncSession,
    AsyncBroker,
    BeatmapFetchTarget,
    BeatmapFreshnessPolicy,
    BeatmapQueryRepository,
    BeatmapMirrorService,
    DirectPointLookupQuery,
    DirectSearchBackend,
    DirectSearchQuery,
    RequestBeatmapFileWarmupUseCase,
    async_sessionmaker,
)

logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


@final
class BeatmapAppProviderSet(Provider):
    """app専用のbeatmap mirrorとworker enqueue連携をAPP scopeで登録する.

    Attributes:
        scope (Scope): app container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def direct_search_backend(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> DirectSearchBackend:
        """設定済みSQL search backendを構成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.

        Returns:
            DirectSearchBackend: candidate IDとscoreだけを返すSQL search backend.
        """
        return ParadeDBSearchBackend(session_factory)

    @provide
    def direct_search_query(
        self,
        repository: BeatmapQueryRepository,
        backend: DirectSearchBackend,
    ) -> DirectSearchQuery:
        """Direct search query use-caseをmetadata repositoryとbackendで構成する.

        Args:
            repository (BeatmapQueryRepository): stable response用metadata source of truth.
            backend (DirectSearchBackend): hydration前候補を返す検索backend.

        Returns:
            DirectSearchQuery: direct search用のread-only query use-case.
        """
        return DirectSearchQuery(repository, backend)

    @provide
    def direct_point_lookup_query(
        self,
        repository: BeatmapQueryRepository,
        eligibility_service: BeatmapEligibilityService,
        freshness_policy: BeatmapFreshnessPolicy,
        broker: AsyncBroker,
        config: AppConfig,
    ) -> DirectPointLookupQuery:
        """Direct point lookup query use-caseをBeatmap Mirror resolverで構成する.

        Args:
            repository (BeatmapQueryRepository): 既存beatmap metadataを読むrepository.
            eligibility_service (BeatmapEligibilityService):
                mirrorで返せるbeatmapを判定するservice.
            freshness_policy (BeatmapFreshnessPolicy): metadataの再取得要否を決めるpolicy.
            broker (AsyncBroker):
                direct point lookup metadata fetchをworkerへenqueueするbroker.
            config (AppConfig): point lookup bounded wait秒数を持つ実行時設定.

        Returns:
            DirectPointLookupQuery: direct point lookup用のread-only query use-case.
        """
        beatmap_resolver = BeatmapMirrorService(
            repository=repository,
            eligibility_service=eligibility_service,
            freshness_policy=freshness_policy,
            mirror_trust_enabled=config.beatmap_mirror_trust_policy == "trusted",
            official_sources_available=config.beatmap_official_sources_enabled,
            enqueue_refresh=lambda target: enqueue_beatmap_fetch(
                broker,
                target,
                direct_point_lookup=True,
            ),
        )
        return DirectPointLookupQuery(
            beatmap_resolver,
            bounded_wait_seconds=config.osu_direct_point_lookup_bounded_wait_seconds,
        )

    @provide
    def beatmap_mirror_service(
        self,
        repository: BeatmapQueryRepository,
        eligibility_service: BeatmapEligibilityService,
        freshness_policy: BeatmapFreshnessPolicy,
        broker: AsyncBroker,
        config: AppConfig,
    ) -> BeatmapMirrorService:
        """Mirror read serviceをtrust policyとfetch enqueue callbackで構成する.

        Args:
            repository (BeatmapQueryRepository): 既存beatmap metadataを読むrepository.
            eligibility_service (BeatmapEligibilityService):
                mirrorで返せるbeatmapを判定するservice.
            freshness_policy (BeatmapFreshnessPolicy): metadataの再取得要否を決めるpolicy.
            broker (AsyncBroker): stale metadataまたはfile fetchをworkerへenqueueするbroker.
            config (AppConfig): mirror trust policyと公式source利用可否を持つ設定.

        Returns:
            BeatmapMirrorService: 必要時に ``enqueue_beatmap_fetch`` を呼ぶapp向けread service.
        """
        return BeatmapMirrorService(
            repository=repository,
            eligibility_service=eligibility_service,
            freshness_policy=freshness_policy,
            mirror_trust_enabled=config.beatmap_mirror_trust_policy == "trusted",
            official_sources_available=config.beatmap_official_sources_enabled,
            enqueue_refresh=lambda target: enqueue_beatmap_fetch(broker, target),
        )

    @provide
    def beatmap_file_warmup_use_case(
        self,
        beatmap_resolver: BeatmapMirrorService,
    ) -> RequestBeatmapFileWarmupUseCase:
        """Beatmap file warmup commandをmirror serviceで構成する.

        Args:
            beatmap_resolver (BeatmapMirrorService):
                file取得対象のbeatmapを解決してenqueueするservice.

        Returns:
            RequestBeatmapFileWarmupUseCase: 必要な ``.osu`` file取得を要求するcommand.
        """
        return RequestBeatmapFileWarmupUseCase(beatmap_resolver)


async def enqueue_beatmap_fetch(
    broker: AsyncBroker,
    target: BeatmapFetchTarget,
    *,
    direct_point_lookup: bool = False,
) -> None:
    """Fetch targetに対応するworker taskを選択してenqueueする.

    Args:
        broker (AsyncBroker): ``fetch_beatmap_file`` と ``fetch_beatmap_metadata`` taskを持つ
            broker.
        target (BeatmapFetchTarget): file fetchかmetadata fetchかと対象keyを表すrequest.
        direct_point_lookup (bool): stable direct point lookup由来のmetadata取得か.

    Returns:
        None: task未登録時はerror logを残して何もenqueueせず,それ以外はenqueue完了後に返す.

    Notes:
        ``force_refresh`` と ``direct_point_lookup`` は真の場合だけkeyword argumentとして渡す.
    """
    task_name = "fetch_beatmap_file" if target.is_file_fetch else "fetch_beatmap_metadata"
    task = broker.find_task(task_name)
    if task is None:
        logger.error(
            "beatmap_fetch_task_not_registered",
            task_name=task_name,
            target_type=target.target_type,
            target_key=target.target_key,
        )
        return

    payload = target.queue_payload()
    kwargs: dict[str, bool] = {}
    if payload.force_refresh:
        kwargs["force_refresh"] = payload.force_refresh
    if direct_point_lookup and not target.is_file_fetch:
        kwargs["direct_point_lookup"] = True
    _ = await task.kiq(payload.target_type, payload.target_key, **kwargs)

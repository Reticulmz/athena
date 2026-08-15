"""app processから利用するbeatmap mirror providerを構成する."""

from __future__ import annotations

from typing import cast, final

import httpx
import structlog
from dishka import Provider, Scope
from meilisearch_python_sdk import AsyncClient as MeilisearchAsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import (
    BeatmapFetchTarget,
    BeatmapFreshnessPolicy,
    DirectSearchBackend,
    DirectSearchUpstreamProvider,
)
from osu_server.infrastructure.beatmaps import (
    CheeseGullDirectSearchUpstreamProvider,
    NerinyanDirectSearchUpstreamProvider,
    SequentialDirectSearchUpstreamProvider,
)
from osu_server.infrastructure.http.beatmap_http_client import (
    BeatmapHttpClient as ConcreteBeatmapHttpClient,
)
from osu_server.infrastructure.search.meilisearch_direct import MeilisearchDirectSearchBackend
from osu_server.jobs.osu_direct import FETCH_OSU_DIRECT_POINT_LOOKUP_METADATA_TASK
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.sqlalchemy.queries.direct_search import (
    AutoDirectSearchBackend,
    ParadeDBSearchBackend,
    TsvectorSearchBackend,
)
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
    DirectSearchUpstreamProvider,
    httpx.AsyncClient,
    MeilisearchAsyncClient,
    RequestBeatmapFileWarmupUseCase,
    async_sessionmaker,
)

logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)
_OSU_DIRECT_UPSTREAM_HEADERS = {"User-Agent": "Athena osu!direct search"}


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
        config: AppConfig,
        meilisearch_client: MeilisearchAsyncClient | None,
    ) -> DirectSearchBackend:
        """設定済みsearch backendを構成する.

        Args:
            session_factory (async_sessionmaker[AsyncSession]): read query用sessionを作るfactory.
            config (AppConfig): search backend選択を持つruntime設定.
            meilisearch_client (MeilisearchAsyncClient | None): Meilisearch SDK client.

        Returns:
            DirectSearchBackend: candidate IDとscoreだけを返すsearch backend.
        """
        if config.osu_direct_search_backend == "paradedb":
            return ParadeDBSearchBackend(session_factory)
        if config.osu_direct_search_backend == "meilisearch":
            return _make_meilisearch_search_backend(config, meilisearch_client)
        if config.osu_direct_search_backend == "tsvector":
            return TsvectorSearchBackend(session_factory)
        backends: list[tuple[str, DirectSearchBackend]] = [
            ("paradedb", ParadeDBSearchBackend(session_factory))
        ]
        if (
            config.osu_direct_external_index_backend == "meilisearch"
            and meilisearch_client is not None
        ):
            backends.append(
                ("meilisearch", _make_meilisearch_search_backend(config, meilisearch_client))
            )
        backends.append(("tsvector", TsvectorSearchBackend(session_factory)))
        return AutoDirectSearchBackend(backends=backends)

    @provide
    def direct_search_query(
        self,
        repository: BeatmapQueryRepository,
        backend: DirectSearchBackend,
        upstream_provider: DirectSearchUpstreamProvider | None,
        broker: AsyncBroker,
        config: AppConfig,
    ) -> DirectSearchQuery:
        """Direct search query use-caseをlocal backendと外部補完で構成する.

        Args:
            repository (BeatmapQueryRepository): stable response用metadata source of truth.
            backend (DirectSearchBackend): hydration前候補を返す検索backend.
            upstream_provider (DirectSearchUpstreamProvider | None):
                local catalog不足時に照会する外部検索provider.
            broker (AsyncBroker): external候補のmetadata fetchをenqueueするbroker.
            config (AppConfig): 外部検索のbounded wait秒数を持つ設定.

        Returns:
            DirectSearchQuery: direct search用のread-only query use-case.
        """

        async def wake_metadata(beatmapset_id: int) -> None:
            """External候補のmetadata fetchをworkerへ要求する.

            Args:
                beatmapset_id (int): fetch対象のbeatmapset ID.

            Returns:
                None: enqueue完了後に値を返さず終了する.
            """
            await enqueue_beatmap_fetch(
                broker,
                BeatmapFetchTarget.metadata_by_beatmapset_id(
                    beatmapset_id,
                    force_refresh=True,
                ),
            )

        return DirectSearchQuery(
            repository,
            backend,
            upstream_provider=upstream_provider,
            coverage_reader=repository,
            upstream_wait_seconds=config.osu_direct_upstream_search_wait_seconds,
            first_page_refresh_seconds=(
                config.osu_direct_upstream_search_first_page_refresh_seconds
            ),
            metadata_wake=wake_metadata,
        )

    @provide
    def direct_search_upstream_provider(
        self,
        config: AppConfig,
        http_client: httpx.AsyncClient,
    ) -> DirectSearchUpstreamProvider | None:
        """設定済みのosu!direct外部検索providerを構成する.

        Args:
            config (AppConfig): 外部検索provider順とendpoint URLを持つ設定.
            http_client (httpx.AsyncClient): APP scopeで共有するHTTP client.

        Returns:
            DirectSearchUpstreamProvider | None: 有効時は順次fallback provider. 無効時はNone.
        """
        return _make_direct_search_upstream_provider(config, http_client)

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

        async def enqueue_refresh(target: BeatmapFetchTarget) -> None:
            """Point lookupのfetch targetを専用metadata taskへenqueueする.

            Args:
                target (BeatmapFetchTarget): point lookup resolverが要求したfetch target.

            Returns:
                None: metadataは専用taskへ,fileは既存taskへenqueueして完了する.
            """
            task_name = (
                "fetch_beatmap_file"
                if target.is_file_fetch
                else FETCH_OSU_DIRECT_POINT_LOOKUP_METADATA_TASK
            )
            await _enqueue_beatmap_fetch_task(broker, target, task_name=task_name)

        beatmap_resolver = BeatmapMirrorService(
            repository=repository,
            eligibility_service=eligibility_service,
            freshness_policy=freshness_policy,
            mirror_trust_enabled=config.beatmap_mirror_trust_policy == "trusted",
            official_sources_available=config.beatmap_official_sources_enabled,
            enqueue_refresh=enqueue_refresh,
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


def _make_meilisearch_search_backend(
    config: AppConfig,
    meilisearch_client: MeilisearchAsyncClient | None,
) -> MeilisearchDirectSearchBackend:
    """Meilisearch search backendを設定済みclientから構成する.

    Args:
        config (AppConfig): Meilisearch index名を持つruntime設定.
        meilisearch_client (MeilisearchAsyncClient | None): Meilisearch SDK client.

    Returns:
        MeilisearchDirectSearchBackend: candidate IDとscoreだけを返すsearch backend.

    Raises:
        RuntimeError: Meilisearch backend指定時にclientが構成されていない場合.
    """
    if meilisearch_client is None:
        msg = "Meilisearch search backend requires osu_direct_meilisearch_url"
        raise RuntimeError(msg)
    return MeilisearchDirectSearchBackend(
        client=meilisearch_client,
        index_name=config.osu_direct_meilisearch_index_name,
    )


def _make_direct_search_upstream_provider(
    config: AppConfig,
    http_client: httpx.AsyncClient,
) -> DirectSearchUpstreamProvider | None:
    """AppConfigからosu!direct外部検索provider chainを構成する.

    Args:
        config (AppConfig): 外部検索の有効状態, provider順, endpoint URLを持つ設定.
        http_client (httpx.AsyncClient): APP scopeで共有するHTTP client.

    Returns:
        DirectSearchUpstreamProvider | None: 有効なprovider chain. 無効または空ならNone.
    """
    if not config.osu_direct_upstream_search_enabled:
        return None

    beatmap_http_client = ConcreteBeatmapHttpClient(http_client)
    providers: list[DirectSearchUpstreamProvider] = []
    for provider_name in config.osu_direct_upstream_search_providers:
        match provider_name:
            case "hinamizawa":
                providers.append(
                    CheeseGullDirectSearchUpstreamProvider(
                        http_client=beatmap_http_client,
                        search_url=config.osu_direct_hinamizawa_search_url,
                        source_label="hinamizawa",
                        headers=_OSU_DIRECT_UPSTREAM_HEADERS,
                    )
                )
            case "nerinyan":
                providers.append(
                    NerinyanDirectSearchUpstreamProvider(
                        http_client=beatmap_http_client,
                        search_url=config.osu_direct_nerinyan_search_url,
                        headers=_OSU_DIRECT_UPSTREAM_HEADERS,
                    )
                )

    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return SequentialDirectSearchUpstreamProvider(providers)


async def enqueue_beatmap_fetch(
    broker: AsyncBroker,
    target: BeatmapFetchTarget,
) -> None:
    """Fetch targetに対応するworker taskを選択してenqueueする.

    Args:
        broker (AsyncBroker): ``fetch_beatmap_file`` と ``fetch_beatmap_metadata`` taskを持つ
            broker.
        target (BeatmapFetchTarget): file fetchかmetadata fetchかと対象keyを表すrequest.

    Returns:
        None: task未登録時はerror logを残して何もenqueueせず,それ以外はenqueue完了後に返す.

    Notes:
        ``force_refresh`` は真の場合だけkeyword argumentとして渡す.
    """
    task_name = "fetch_beatmap_file" if target.is_file_fetch else "fetch_beatmap_metadata"
    await _enqueue_beatmap_fetch_task(broker, target, task_name=task_name)


async def _enqueue_beatmap_fetch_task(
    broker: AsyncBroker,
    target: BeatmapFetchTarget,
    *,
    task_name: str,
) -> None:
    """指定taskへBeatmapFetchTargetのprimitive payloadをenqueueする.

    Args:
        broker (AsyncBroker): taskを名前で解決してenqueueするbroker.
        target (BeatmapFetchTarget): queue payloadへ変換するfetch target.
        task_name (str): enqueue先の登録済みTaskiq task名.

    Returns:
        None: task未登録時はerror logを残し,登録済みならenqueueして完了する.
    """
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
    _ = await task.kiq(payload.target_type, payload.target_key, **kwargs)

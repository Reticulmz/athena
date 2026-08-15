"""worker processから利用するosu!direct beatmap command providerを構成する."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import httpx
from dishka import Provider, Scope
from meilisearch_python_sdk import AsyncClient as MeilisearchAsyncClient

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import (
    BeatmapMetadataProvider,
    BeatmapMetadataSource,
    DirectCoverageStatusScope,
    DirectExternalIndexBackend,
)
from osu_server.infrastructure.beatmaps import OsuApiMetadataProviderService
from osu_server.infrastructure.beatmaps.metadata_source_adapters import (
    MirrorMetadataProviderService,
)
from osu_server.infrastructure.http.beatmap_http_client import (
    BeatmapHttpClient as ConcreteBeatmapHttpClient,
)
from osu_server.infrastructure.search.meilisearch_direct import MeilisearchDirectIndexBackend
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.beatmaps.direct_catalog_sync import (
    DirectCatalogScheduler,
    DirectFeedSync,
    DirectFeedWindow,
    DirectFeedWindowFetchResult,
    DirectRangeCrawl,
    DirectRangeCrawlChunk,
    DirectRangeCrawlFetchResult,
)
from osu_server.services.commands.beatmaps.direct_indexing import (
    DirectExternalIndexWriter,
    DirectIndexingCommands,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import BeatmapsetSnapshot

_OFFICIAL_FEED_STATUS_VALUES = {
    DirectCoverageStatusScope.ALL: "any",
    DirectCoverageStatusScope.RANKED: "ranked",
    DirectCoverageStatusScope.LOVED: "loved",
    DirectCoverageStatusScope.QUALIFIED: "qualified",
    DirectCoverageStatusScope.PENDING: "pending",
    DirectCoverageStatusScope.WIP: "wip",
    DirectCoverageStatusScope.GRAVEYARD: "graveyard",
}

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    BeatmapMetadataProvider,
    DirectCatalogScheduler,
    DirectFeedSync,
    DirectIndexingCommands,
    DirectRangeCrawl,
    UnitOfWorkFactory,
    MeilisearchAsyncClient,
    httpx.AsyncClient,
)


class DirectCatalogFetcher:
    """worker catalog sync use-caseへupstream metadata fetchを提供するadapter.

    Attributes:
        _official_provider (OsuApiMetadataProviderService | None): feed windowで使う公式検索
            provider.
        _mirror_provider (BeatmapMetadataProvider): mirror range crawlで使うprovider.
        _mirror_lookup_request_count (int): mirror ID lookup 1件で試行しうるHTTP request数.
            0ならmirror source未設定.
    """

    _official_provider: OsuApiMetadataProviderService | None
    _mirror_provider: BeatmapMetadataProvider
    _mirror_lookup_request_count: int

    def __init__(
        self,
        *,
        official_provider: OsuApiMetadataProviderService | None,
        mirror_provider: BeatmapMetadataProvider,
        mirror_lookup_request_count: int = 1,
    ) -> None:
        """Catalog fetch adapterの参照を保持する.

        Args:
            official_provider (OsuApiMetadataProviderService | None): feed search用provider.
            mirror_provider (BeatmapMetadataProvider): mirror source指定時のprovider.
            mirror_lookup_request_count (int): mirror fallbackを含む1 IDあたりの最大試行数.
                0ならmirror source未設定.

        Raises:
            ValueError: mirror_lookup_request_countが負値の場合.
        """
        if mirror_lookup_request_count < 0:
            msg = "mirror_lookup_request_count must not be negative"
            raise ValueError(msg)
        self._official_provider = official_provider
        self._mirror_provider = mirror_provider
        self._mirror_lookup_request_count = mirror_lookup_request_count

    def request_count_for_chunk(self, chunk: DirectRangeCrawlChunk) -> int:
        """ID range crawlが消費しうるupstream request数を返す.

        Args:
            chunk (DirectRangeCrawlChunk): crawl対象のid range chunk.

        Returns:
            int: mirror fallbackではbase URL数を掛けた最大HTTP試行数. officialでは
            token取得を含む最大HTTP試行数.

        Raises:
            RuntimeError: mirror sourceが要求されたがmirror base URLが未設定の場合.
        """
        range_size = chunk.to_beatmapset_id - chunk.from_beatmapset_id + 1
        if chunk.source is BeatmapMetadataSource.MIRROR:
            if self._mirror_lookup_request_count == 0:
                msg = "mirror metadata source is not configured"
                raise RuntimeError(msg)
            return range_size * self._mirror_lookup_request_count
        return range_size + 1

    async def fetch_feed_window(
        self,
        window: DirectFeedWindow,
    ) -> DirectFeedWindowFetchResult:
        """公式beatmapset searchからfeed windowのsnapshot列を取得する.

        Args:
            window (DirectFeedWindow): source,status,sort,pageを持つfeed window scope.

        Returns:
            DirectFeedWindowFetchResult: 取得したsnapshot列と次cursor.

        Raises:
            RuntimeError: 公式feed sourceが設定されていない場合.
            ValueError: windowが公式searchで表現できないstatusまたはpageを持つ場合.
        """
        if window.source is not BeatmapMetadataSource.OFFICIAL:
            msg = "direct feed window sync requires official metadata source"
            raise RuntimeError(msg)
        if self._official_provider is None:
            msg = "official beatmapset search is not configured"
            raise RuntimeError(msg)

        result = await self._official_provider.search_beatmapsets(_feed_search_params(window))
        return DirectFeedWindowFetchResult(
            beatmapsets=result.beatmapsets,
            cursor=result.cursor,
        )

    async def fetch_id_range(
        self,
        chunk: DirectRangeCrawlChunk,
    ) -> DirectRangeCrawlFetchResult:
        """既存metadata providerでbeatmapset ID rangeを取得する.

        Args:
            chunk (DirectRangeCrawlChunk): 取得するbeatmapset ID range.

        Returns:
            DirectRangeCrawlFetchResult: 見つかったsnapshotだけを含むrange結果.

        Raises:
            RuntimeError: requested sourceのproviderが構成されていない場合.
        """
        snapshots: list[BeatmapsetSnapshot] = []
        provider = self._range_provider(chunk.source)
        for beatmapset_id in range(chunk.from_beatmapset_id, chunk.to_beatmapset_id + 1):
            snapshot = await provider.lookup_by_beatmapset_id(beatmapset_id)
            if snapshot is not None:
                snapshots.append(snapshot)
        return DirectRangeCrawlFetchResult(beatmapsets=tuple(snapshots))

    def _range_provider(self, source: BeatmapMetadataSource) -> BeatmapMetadataProvider:
        """Coverage sourceに一致するmetadata providerを返す.

        Args:
            source (BeatmapMetadataSource): chunkがcoverageへ記録するsource.

        Returns:
            BeatmapMetadataProvider: sourceに対応するprovider.

        Raises:
            RuntimeError: sourceに対応するproviderが無効な場合.
        """
        if source is BeatmapMetadataSource.MIRROR:
            if self._mirror_lookup_request_count == 0:
                msg = "mirror metadata source is not configured"
                raise RuntimeError(msg)
            return self._mirror_provider
        if self._official_provider is None:
            msg = "official metadata source is not configured"
            raise RuntimeError(msg)
        return self._official_provider


@final
class BeatmapWorkerProviderSet(Provider):
    """worker専用のosu!direct schedulerとindexing commandをAPP scopeで登録する.

    Attributes:
        scope (Scope): worker container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def direct_catalog_scheduler(self, config: AppConfig) -> DirectCatalogScheduler:
        """設定された共有upstream budgetでcatalog schedulerを構成する.

        Args:
            config (AppConfig): osu!directの共有upstream budget設定を持つ実行時設定.

        Returns:
            DirectCatalogScheduler: point lookup優先の共有budget scheduler.
        """
        return DirectCatalogScheduler(
            request_budget_per_minute=config.osu_direct_shared_upstream_budget_per_minute
        )

    @provide
    def direct_catalog_fetcher(
        self,
        config: AppConfig,
        http_client: httpx.AsyncClient,
    ) -> DirectCatalogFetcher:
        """Worker catalog sync用のfeed/range fetch adapterを構成する.

        Args:
            config (AppConfig): 公式API credentialとsource availabilityを持つ設定.
            http_client (httpx.AsyncClient): 公式API検索で再利用するHTTP client.

        Returns:
            DirectCatalogFetcher: feed windowとid rangeを取得するadapter.
        """
        official_provider = (
            OsuApiMetadataProviderService(
                client_id=config.beatmap_official_api_client_id or "",
                client_secret=config.beatmap_official_api_client_secret or "",
                http_client=ConcreteBeatmapHttpClient(http_client),
            )
            if config.beatmap_official_sources_enabled
            else None
        )
        mirror_provider = MirrorMetadataProviderService(
            http_client=ConcreteBeatmapHttpClient(http_client),
            base_urls=config.beatmap_metadata_mirror_base_urls,
        )
        return DirectCatalogFetcher(
            official_provider=official_provider,
            mirror_provider=mirror_provider,
            mirror_lookup_request_count=len(config.beatmap_metadata_mirror_base_urls),
        )

    @provide
    def direct_feed_sync(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        scheduler: DirectCatalogScheduler,
        fetcher: DirectCatalogFetcher,
    ) -> DirectFeedSync:
        """Feed window catalog sync use-caseをworker用に構成する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): metadataとcoverage保存用factory.
            scheduler (DirectCatalogScheduler): shared upstream budget scheduler.
            fetcher (DirectCatalogFetcher): feed window metadata fetch adapter.

        Returns:
            DirectFeedSync: worker jobから実行するfeed sync use-case.
        """
        return DirectFeedSync(
            unit_of_work_factory=unit_of_work_factory,
            scheduler=scheduler,
            feed_window_fetcher=fetcher,
        )

    @provide
    def direct_range_crawl(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        scheduler: DirectCatalogScheduler,
        fetcher: DirectCatalogFetcher,
    ) -> DirectRangeCrawl:
        """ID range catalog crawl use-caseをworker用に構成する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): metadataとcoverage保存用factory.
            scheduler (DirectCatalogScheduler): shared upstream budget scheduler.
            fetcher (DirectCatalogFetcher): id range metadata fetch adapter.

        Returns:
            DirectRangeCrawl: worker jobから実行するrange crawl use-case.
        """
        return DirectRangeCrawl(
            unit_of_work_factory=unit_of_work_factory,
            scheduler=scheduler,
            range_crawl_fetcher=fetcher,
        )

    @provide
    def direct_indexing_commands(
        self,
        config: AppConfig,
        unit_of_work_factory: UnitOfWorkFactory,
        meilisearch_client: MeilisearchAsyncClient | None,
    ) -> DirectIndexingCommands:
        """Projection/external index commandをworker runtime用に構成する.

        Args:
            config (AppConfig): optional external index backend設定を持つ実行時設定.
            unit_of_work_factory (UnitOfWorkFactory): command transactionを開くfactory.
            meilisearch_client (MeilisearchAsyncClient | None): Meilisearch SDK client.

        Returns:
            DirectIndexingCommands: rebuildとexternal index update用command.
        """
        return DirectIndexingCommands(
            unit_of_work_factory=unit_of_work_factory,
            external_index_backend=_make_external_index_backend(config, meilisearch_client),
            backend=DirectExternalIndexBackend.MEILISEARCH,
        )


def _feed_search_params(window: DirectFeedWindow) -> dict[str, str]:
    """Feed window scopeを公式beatmapset search queryへ変換する.

    Args:
        window (DirectFeedWindow): status, sort, page markerを持つfeed window.

    Returns:
        dict[str, str]: 公式APIへ渡すquery parameters.

    Raises:
        ValueError: status scopeまたはwindow keyが公式API queryへ変換できない場合.
    """
    status = _OFFICIAL_FEED_STATUS_VALUES.get(window.status_scope)
    if status is None:
        msg = f"unsupported official feed status scope: {window.status_scope.value}"
        raise ValueError(msg)
    return {
        "s": status,
        "page": _feed_page(window.window_key),
        "sort": _feed_sort(window.sort_key),
    }


def _feed_page(window_key: str) -> str:
    """Feed window keyから公式search page値を返す.

    Args:
        window_key (str): 数値または `page-<number>` のpage marker.

    Returns:
        str: 公式API queryへ渡すpage番号.

    Raises:
        ValueError: window keyが正のpage番号でない場合.
    """
    raw_page = window_key.removeprefix("page-")
    try:
        page = int(raw_page)
    except ValueError as exc:
        msg = "official feed window_key must be a page number"
        raise ValueError(msg) from exc
    if page <= 0:
        msg = "official feed window_key must be a positive page number"
        raise ValueError(msg)
    return str(page)


def _feed_sort(sort_key: str) -> str:
    """Feed sort keyを公式search sort parameterへ変換する.

    Args:
        sort_key (str): `ranked` または `ranked_desc` などのsort識別子.

    Returns:
        str: 公式APIへ渡すsort parameter.
    """
    if sort_key.endswith(("_asc", "_desc")):
        return sort_key
    return f"{sort_key}_desc"


def _make_external_index_backend(
    config: AppConfig,
    meilisearch_client: MeilisearchAsyncClient | None,
) -> DirectExternalIndexWriter | None:
    """設定に応じてoptional external index adapterを作成する.

    Args:
        config (AppConfig): external index backendとMeilisearch接続設定.
        meilisearch_client (MeilisearchAsyncClient | None): Meilisearch SDK client.

    Returns:
        DirectExternalIndexWriter | None: disabledならNone, Meilisearchならadapter.
    """
    if config.osu_direct_external_index_backend == "disabled" or meilisearch_client is None:
        return None
    return MeilisearchDirectIndexBackend(
        client=meilisearch_client,
        index_name=config.osu_direct_meilisearch_index_name,
    )


__all__ = ["BeatmapWorkerProviderSet"]

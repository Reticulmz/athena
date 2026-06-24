"""Shared beatmap providers for app and worker dependency graphs."""

from __future__ import annotations

from datetime import timedelta
from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import (
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
)
from osu_server.infrastructure.http.beatmap_http_client import (
    BeatmapHttpClient as ConcreteBeatmapHttpClient,
)
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.commands.storage.blob_storage import BlobStorageService
from osu_server.services.queries.beatmaps import (
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapFileProviderService,
    MirrorMetadataProviderService,
    OsuApiMetadataProviderService,
)
from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
)

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
    BeatmapLeaderboardRebuildWorkerWake,
    BeatmapQueryRepository,
    BlobStorageService,
    UnitOfWorkFactory,
)


@final
class BeatmapProviderSet(Provider):
    """Providers for shared beatmap policies, queries, and fetch workflows."""

    scope = Scope.APP

    @provide
    def beatmap_freshness_policy(self, config: AppConfig) -> BeatmapFreshnessPolicy:
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
        return BeatmapFileProviderService(
            http_client=ConcreteBeatmapHttpClient(),
            osu_current_url_template=config.beatmap_osu_current_url_template,
            osu_legacy_url_template=config.beatmap_osu_legacy_url_template,
            mirror_url_templates=list(config.beatmap_community_mirror_url_templates),
        )

    @provide
    def beatmap_eligibility_service(self) -> BeatmapEligibilityService:
        return BeatmapEligibilityService()

    @provide
    def resolve_beatmap_by_id_query(
        self,
        repository: BeatmapQueryRepository,
    ) -> ResolveBeatmapByIdQuery:
        return ResolveBeatmapByIdQuery(repository)

    @provide
    def resolve_beatmap_by_checksum_query(
        self,
        repository: BeatmapQueryRepository,
    ) -> ResolveBeatmapByChecksumQuery:
        return ResolveBeatmapByChecksumQuery(repository)

    @provide
    def fetch_beatmap_metadata_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
        metadata_provider: BeatmapMetadataProvider,
        freshness_policy: BeatmapFreshnessPolicy,
        config: AppConfig,
        leaderboard_rebuild_wake: BeatmapLeaderboardRebuildWorkerWake,
    ) -> FetchBeatmapMetadataUseCase:
        """metadata fetch use-case を freshness policy と共に構成する。"""
        return FetchBeatmapMetadataUseCase(
            uow_factory=uow_factory,
            metadata_provider=metadata_provider,
            freshness_policy=freshness_policy,
            official_sources_available=config.beatmap_official_sources_enabled,
            leaderboard_rebuild_wake=leaderboard_rebuild_wake,
        )

    @provide
    def fetch_beatmap_file_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
        file_provider: BeatmapFileProvider,
        blob_storage: BlobStorageService,
    ) -> FetchBeatmapFileUseCase:
        return FetchBeatmapFileUseCase(
            uow_factory=uow_factory,
            file_provider=file_provider,
            blob_storage=blob_storage,
        )

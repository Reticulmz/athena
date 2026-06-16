"""Performance subsystem providers shared by app and worker graphs."""

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
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignal,
)
from osu_server.infrastructure.state.valkey.performance_completion_signal import (
    ValkeyPerformanceCompletionPublisher,
    ValkeyPerformanceCompletionSignal,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.services.commands.scores.performance import (
    BeatmapMirrorPerformanceBeatmapFileProvider,
    PerformanceBeatmapFileProvider,
    PerformanceRuntimeSettings,
)
from osu_server.services.commands.storage import BlobStorageService
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)

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
    PerformanceCompletionSignal,
    PerformanceRuntimeSettings,
    ValkeyPerformanceCompletionPublisher,
)


@final
class PerformanceProviderSet(Provider):
    """Providers for score performance runtime defaults and policies."""

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
    def performance_beatmap_file_provider(
        self,
        repository: BeatmapQueryRepository,
        eligibility_service: BeatmapEligibilityService,
        freshness_policy: BeatmapFreshnessPolicy,
        broker: AsyncBroker,
        config: AppConfig,
        blob_storage: BlobStorageService,
    ) -> PerformanceBeatmapFileProvider:
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
        return valkey

    @provide
    def performance_completion_signal(
        self,
        publisher: ValkeyPerformanceCompletionPublisher,
        config: AppConfig,
    ) -> PerformanceCompletionSignal:
        valkey_url = str(config.valkey_url)

        async def pubsub_client_factory(callback: ValkeyPubSubCallback) -> GlideClient:
            return await create_valkey_pubsub_client(valkey_url, callback)

        return ValkeyPerformanceCompletionSignal(
            publisher,
            pubsub_client_factory=pubsub_client_factory,
        )

"""App-facing beatmap mirror providers."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.beatmaps import BeatmapFetchTarget, BeatmapFreshnessPolicy
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    AsyncBroker,
    BeatmapFetchTarget,
    BeatmapFreshnessPolicy,
    BeatmapQueryRepository,
)


@final
class BeatmapAppProviderSet(Provider):
    """Providers for app-only beatmap mirror and enqueue integration."""

    scope = Scope.APP

    @provide
    def beatmap_mirror_service(
        self,
        repository: BeatmapQueryRepository,
        eligibility_service: BeatmapEligibilityService,
        freshness_policy: BeatmapFreshnessPolicy,
        broker: AsyncBroker,
        config: AppConfig,
    ) -> BeatmapMirrorService:
        return BeatmapMirrorService(
            repository=repository,
            eligibility_service=eligibility_service,
            freshness_policy=freshness_policy,
            mirror_trust_enabled=config.beatmap_mirror_trust_policy == "trusted",
            official_sources_available=config.beatmap_official_sources_enabled,
            enqueue_refresh=lambda target: enqueue_beatmap_fetch(broker, target),
        )


async def enqueue_beatmap_fetch(broker: AsyncBroker, target: BeatmapFetchTarget) -> None:
    """Enqueue the worker job matching a beatmap fetch target."""
    if target.target_type.startswith("file:"):
        task_name = "fetch_beatmap_file"
    else:
        task_name = "fetch_beatmap_metadata"
    task = broker.find_task(task_name)
    if task is None:
        return

    _ = await task.kiq(target.target_type, target.target_key)

"""Shared score providers for app and worker dependency graphs."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.jobs.beatmap_leaderboards import TaskiqBeatmapLeaderboardRebuildWorkerWake
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserUseCase,
)
from osu_server.services.queries.scores import BeatmapLeaderboardQuery, BeatmapScoreListingQuery
from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
)

_DISHKA_RUNTIME_HINTS = (
    AsyncBroker,
    BeatmapLeaderboardQuery,
    BeatmapLeaderboardQueryRepository,
    BeatmapLeaderboardRebuildWorkerWake,
    BeatmapScoreListingQueryRepository,
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserUseCase,
    TaskiqBeatmapLeaderboardRebuildWorkerWake,
    UnitOfWorkFactory,
)


@final
class ScoreProviderSet(Provider):
    """Providers for shared score helpers and read-side score queries."""

    scope = Scope.APP

    @provide
    def score_crypto_service(self) -> ScoreCryptoService:
        return ScoreCryptoService()

    @provide
    def beatmap_score_listing_query(
        self,
        leaderboard_query: BeatmapLeaderboardQuery,
    ) -> BeatmapScoreListingQuery:
        return BeatmapScoreListingQuery(leaderboard_query)

    @provide
    def beatmap_leaderboard_query(
        self,
        repository: BeatmapScoreListingQueryRepository,
        leaderboards: BeatmapLeaderboardQueryRepository,
    ) -> BeatmapLeaderboardQuery:
        return BeatmapLeaderboardQuery(
            repository,
            leaderboards,
        )

    @provide
    def beatmap_leaderboard_rebuild_worker_wake(
        self,
        broker: AsyncBroker,
    ) -> BeatmapLeaderboardRebuildWorkerWake:
        return TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

    @provide
    def rebuild_beatmap_leaderboards_for_user_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> RebuildBeatmapLeaderboardsForUserUseCase:
        return RebuildBeatmapLeaderboardsForUserUseCase(uow_factory)

    @provide
    def rebuild_beatmap_leaderboards_for_beatmapset_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> RebuildBeatmapLeaderboardsForBeatmapsetUseCase:
        return RebuildBeatmapLeaderboardsForBeatmapsetUseCase(uow_factory)

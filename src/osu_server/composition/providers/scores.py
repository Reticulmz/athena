"""Shared score providers for app and worker dependency graphs."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope
from taskiq import AsyncBroker

from osu_server.composition.providers._dishka import provide
from osu_server.domain.compatibility.stable import ReplayDownloadBodyStrategy
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.infrastructure.state.interfaces.replay_download_accounting_gate import (
    ReplayDownloadAccountingGate,
)
from osu_server.jobs.beatmap_leaderboards import TaskiqBeatmapLeaderboardRebuildWorkerWake
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadQueryRepository,
)
from osu_server.repositories.interfaces.queries.user_stats import UserStatsQueryRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserUseCase,
)
from osu_server.services.commands.scores.replay_download_accounting import (
    ReplayDownloadAccountingUseCase,
)
from osu_server.services.queries.scores import (
    BeatmapLeaderboardQuery,
    BeatmapPersonalBestRankQuery,
    BeatmapScoreListingQuery,
    CurrentUserStatsQuery,
    ReplayDownloadBodyAssembler,
    ReplayDownloadQuery,
)
from osu_server.services.queries.storage import BlobByteReader
from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
)

_DISHKA_RUNTIME_HINTS = (
    AsyncBroker,
    BeatmapLeaderboardQuery,
    BeatmapLeaderboardQueryRepository,
    BeatmapLeaderboardRebuildWorkerWake,
    BeatmapPersonalBestRankQuery,
    BeatmapScoreListingQueryRepository,
    BlobByteReader,
    CurrentUserStatsQuery,
    ReplayDownloadAccountingGate,
    ReplayDownloadAccountingUseCase,
    ReplayDownloadBodyAssembler,
    ReplayDownloadQuery,
    ReplayDownloadQueryRepository,
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserUseCase,
    TaskiqBeatmapLeaderboardRebuildWorkerWake,
    UnitOfWorkFactory,
    UserStatsQueryRepository,
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
    def beatmap_personal_best_rank_query(
        self,
        leaderboards: BeatmapLeaderboardQueryRepository,
    ) -> BeatmapPersonalBestRankQuery:
        return BeatmapPersonalBestRankQuery(leaderboards)

    @provide
    def current_user_stats_query(
        self,
        repository: UserStatsQueryRepository,
    ) -> CurrentUserStatsQuery:
        return CurrentUserStatsQuery(repository=repository)

    @provide
    def replay_download_body_assembler(self) -> ReplayDownloadBodyAssembler:
        return ReplayDownloadBodyAssembler()

    @provide
    def replay_download_query(
        self,
        repository: ReplayDownloadQueryRepository,
        blob_reader: BlobByteReader,
        body_assembler: ReplayDownloadBodyAssembler,
    ) -> ReplayDownloadQuery:
        return ReplayDownloadQuery(
            repository=repository,
            blob_reader=blob_reader,
            body_assembler=body_assembler,
            body_strategy=ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES,
        )

    @provide
    def replay_download_accounting(
        self,
        uow_factory: UnitOfWorkFactory,
        accounting_gate: ReplayDownloadAccountingGate,
    ) -> ReplayDownloadAccountingUseCase:
        return ReplayDownloadAccountingUseCase(
            unit_of_work_factory=uow_factory,
            accounting_gate=accounting_gate,
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

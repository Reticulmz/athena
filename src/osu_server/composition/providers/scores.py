"""appとworkerで共有するscore providerを構成する."""

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
from osu_server.jobs.replay_download_accounting import TaskiqReplayDownloadAccountingPublisher
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
    ReplayDownloadAccountingPublisher,
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
    ReplayDownloadAccountingPublisher,
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
    """共有score helper、query、worker wake portをAPP scopeで登録する.

    Attributes:
        scope (Scope): appとworker container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def score_crypto_service(self) -> ScoreCryptoService:
        """Score payloadの暗号処理serviceを構成する.

        Returns:
            ScoreCryptoService: stable score payloadの復号に使うcrypto service.
        """
        return ScoreCryptoService()

    @provide
    def beatmap_score_listing_query(
        self,
        leaderboard_query: BeatmapLeaderboardQuery,
    ) -> BeatmapScoreListingQuery:
        """Legacy score list表示用queryをleaderboard queryから構成する.

        Args:
            leaderboard_query (BeatmapLeaderboardQuery): filtered leaderboardを構成するquery.

        Returns:
            BeatmapScoreListingQuery: getscores向けscore listを取得するquery.
        """
        return BeatmapScoreListingQuery(leaderboard_query)

    @provide
    def beatmap_leaderboard_query(
        self,
        repository: BeatmapScoreListingQueryRepository,
        leaderboards: BeatmapLeaderboardQueryRepository,
    ) -> BeatmapLeaderboardQuery:
        """Beatmap leaderboard queryをscore listとleaderboard read repositoryで構成する.

        Args:
            repository (BeatmapScoreListingQueryRepository):
                beatmapごとのscore listを読むrepository.
            leaderboards (BeatmapLeaderboardQueryRepository):
                materialized leaderboardを読むrepository.

        Returns:
            BeatmapLeaderboardQuery: visibilityとrankingを考慮したleaderboardを取得するquery.
        """
        return BeatmapLeaderboardQuery(
            repository,
            leaderboards,
        )

    @provide
    def beatmap_personal_best_rank_query(
        self,
        leaderboards: BeatmapLeaderboardQueryRepository,
    ) -> BeatmapPersonalBestRankQuery:
        """beatmap内personal best rankを取得するqueryを構成する.

        Args:
            leaderboards (BeatmapLeaderboardQueryRepository):
                materialized leaderboardを読むrepository.

        Returns:
            BeatmapPersonalBestRankQuery: userのbeatmap内順位を取得するquery.
        """
        return BeatmapPersonalBestRankQuery(leaderboards)

    @provide
    def current_user_stats_query(
        self,
        repository: UserStatsQueryRepository,
    ) -> CurrentUserStatsQuery:
        """Current user statsを取得するqueryを構成する.

        Args:
            repository (UserStatsQueryRepository): user stats projectionを読むrepository.

        Returns:
            CurrentUserStatsQuery: current score statsを取得するquery.
        """
        return CurrentUserStatsQuery(repository=repository)

    @provide
    def replay_download_body_assembler(self) -> ReplayDownloadBodyAssembler:
        """Replay download response bodyを組み立てるassemblerを構成する.

        Returns:
            ReplayDownloadBodyAssembler: replay blobをlegacy response bodyへ変換するassembler.
        """
        return ReplayDownloadBodyAssembler()

    @provide
    def replay_download_query(
        self,
        repository: ReplayDownloadQueryRepository,
        blob_reader: BlobByteReader,
        body_assembler: ReplayDownloadBodyAssembler,
    ) -> ReplayDownloadQuery:
        """Replay download queryをread repository、blob reader、body strategyで構成する.

        Args:
            repository (ReplayDownloadQueryRepository): replay metadataと可視性を読むrepository.
            blob_reader (BlobByteReader): replay blob bytesを取得するport.
            body_assembler (ReplayDownloadBodyAssembler):
                blob bytesからresponse bodyを組み立てるassembler.

        Returns:
            ReplayDownloadQuery: stable legacy response用replayを取得するquery.

        Notes:
            body strategyは ``ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES`` に固定する.
        """
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
        """Replay download accounting commandをtransactionとdeduplication gateで構成する.

        Args:
            uow_factory (UnitOfWorkFactory): view count更新をtransactionで実行するfactory.
            accounting_gate (ReplayDownloadAccountingGate): 同一downloadの重複計上を防ぐgate.

        Returns:
            ReplayDownloadAccountingUseCase: successful replay downloadを非同期で計上するcommand.
        """
        return ReplayDownloadAccountingUseCase(
            unit_of_work_factory=uow_factory,
            accounting_gate=accounting_gate,
        )

    @provide
    def replay_download_accounting_publisher(
        self,
        broker: AsyncBroker,
    ) -> ReplayDownloadAccountingPublisher:
        """Replay download accounting workをTaskiqへpublishするportを構成する.

        Args:
            broker (AsyncBroker): accounting taskをenqueueするTaskiq broker.

        Returns:
            ReplayDownloadAccountingPublisher: replay view accountingをworkerへ配送するpublisher.
        """
        return TaskiqReplayDownloadAccountingPublisher(broker)

    @provide
    def beatmap_leaderboard_rebuild_worker_wake(
        self,
        broker: AsyncBroker,
    ) -> BeatmapLeaderboardRebuildWorkerWake:
        """Leaderboard rebuild workerを起動するTaskiq portを構成する.

        Args:
            broker (AsyncBroker): leaderboard rebuild taskをenqueueするTaskiq broker.

        Returns:
            BeatmapLeaderboardRebuildWorkerWake: userまたはbeatmapset rebuildをworkerへ
                要求するport.
        """
        return TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

    @provide
    def rebuild_beatmap_leaderboards_for_user_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> RebuildBeatmapLeaderboardsForUserUseCase:
        """user単位のbeatmap leaderboard rebuild commandを構成する.

        Args:
            uow_factory (UnitOfWorkFactory): leaderboard projection更新をtransactionで行うfactory.

        Returns:
            RebuildBeatmapLeaderboardsForUserUseCase: 一人のscore更新に対応するrebuild command.
        """
        return RebuildBeatmapLeaderboardsForUserUseCase(uow_factory)

    @provide
    def rebuild_beatmap_leaderboards_for_beatmapset_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> RebuildBeatmapLeaderboardsForBeatmapsetUseCase:
        """beatmapset単位のbeatmap leaderboard rebuild commandを構成する.

        Args:
            uow_factory (UnitOfWorkFactory): leaderboard projection更新をtransactionで行うfactory.

        Returns:
            RebuildBeatmapLeaderboardsForBeatmapsetUseCase: beatmapset全体をrebuildするcommand.
        """
        return RebuildBeatmapLeaderboardsForBeatmapsetUseCase(uow_factory)

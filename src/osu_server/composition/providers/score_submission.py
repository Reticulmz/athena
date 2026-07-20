"""app process専用のscore submission providerを構成する."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.infrastructure.performance.interfaces import PerformanceCalculator
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
from osu_server.services.commands.scores import ProcessScoreSubmissionUseCase, SubmitScoreUseCase
from osu_server.services.commands.scores.authorization import ScoreAuthorizationService
from osu_server.services.commands.scores.performance import RequestPerformanceCalculationUseCase
from osu_server.services.commands.storage.blob_storage import BlobStorageService
from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.scores import (
    BeatmapPersonalBestRankQuery,
    CurrentUserStatsQuery,
    PerformanceResponseQuery,
)

_DISHKA_RUNTIME_HINTS = (
    BeatmapMirrorService,
    BlobStorageService,
    PasswordService,
    PerformanceCalculator,
    PerformanceResponseQuery,
    BeatmapPersonalBestRankQuery,
    CurrentUserStatsQuery,
    RequestPerformanceCalculationUseCase,
    SessionStore,
    SubmitScoreUseCase,
    RequestBeatmapFileWarmupUseCase,
    UnitOfWorkFactory,
    UserQueryRepository,
)


@final
class ScoreSubmissionProviderSet(Provider):
    """score認可とsubmission処理workflowをAPP scopeで登録する.

    Attributes:
        scope (Scope): app container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def score_authorization_service(
        self,
        user_repo: UserQueryRepository,
        password_service: PasswordService,
        session_store: SessionStore,
    ) -> ScoreAuthorizationService:
        """Stable score submissionの認可serviceをidentity依存で構成する.

        Args:
            user_repo (UserQueryRepository): submission userを検索するread repository.
            password_service (PasswordService): password hashの照合を行うquery service.
            session_store (SessionStore): active sessionを検証するvolatile store.

        Returns:
            ScoreAuthorizationService: score submissionのuser credentialとsessionを認可するservice.
        """
        return ScoreAuthorizationService(
            user_repo=user_repo,
            password_service=password_service,
            session_store=session_store,
        )

    @provide
    def submit_score_use_case(self, uow_factory: UnitOfWorkFactory) -> SubmitScoreUseCase:
        """score永続化commandをUnit of Work factoryで構成する.

        Args:
            uow_factory (UnitOfWorkFactory): score mutationをtransactionで実行するfactory.

        Returns:
            SubmitScoreUseCase: 正規化済みscore submissionを永続化するcommand.
        """
        return SubmitScoreUseCase(unit_of_work_factory=uow_factory)

    @provide
    def process_score_submission_use_case(
        self,
        submit_score_use_case: SubmitScoreUseCase,
        replay_blob_storage: BlobStorageService,
        auth_service: ScoreAuthorizationService,
        beatmap_resolver: BeatmapMirrorService,
        beatmap_file_warmup: RequestBeatmapFileWarmupUseCase,
        performance_calculation_request: RequestPerformanceCalculationUseCase,
        performance_calculator: PerformanceCalculator,
        performance_response_query: PerformanceResponseQuery,
        current_user_stats_query: CurrentUserStatsQuery,
        beatmap_personal_best_rank_query: BeatmapPersonalBestRankQuery,
    ) -> ProcessScoreSubmissionUseCase:
        """Score submission全体workflowを認可、beatmap、replay、performance依存で構成する.

        Args:
            submit_score_use_case (SubmitScoreUseCase): 正規化済みscoreを永続化するcommand.
            replay_blob_storage (BlobStorageService): replay blobを保存するstorage service.
            auth_service (ScoreAuthorizationService): submission credentialを検証するservice.
            beatmap_resolver (BeatmapMirrorService): submission対象beatmapを解決するservice.
            beatmap_file_warmup (RequestBeatmapFileWarmupUseCase):
                不足するbeatmap file取得を要求するcommand.
            performance_calculation_request (RequestPerformanceCalculationUseCase):
                performance計算を要求するcommand.
            performance_calculator (PerformanceCalculator):
                score performanceを計算するadapter identity.
            performance_response_query (PerformanceResponseQuery):
                計算済みperformanceのresponseを取得するquery.
            current_user_stats_query (CurrentUserStatsQuery):
                submission後のuser statsを取得するquery.
            beatmap_personal_best_rank_query (BeatmapPersonalBestRankQuery):
                beatmap内personal best rankを取得するquery.

        Returns:
            ProcessScoreSubmissionUseCase: stable submissionを認可、保存、response生成まで
                処理するcommand.
        """
        return ProcessScoreSubmissionUseCase(
            submit_score_use_case=submit_score_use_case,
            replay_blob_storage=replay_blob_storage,
            auth_service=auth_service,
            beatmap_resolver=beatmap_resolver,
            beatmap_file_warmup_use_case=beatmap_file_warmup,
            performance_calculation_request=performance_calculation_request,
            performance_calculator_identity=performance_calculator,
            performance_response_query=performance_response_query,
            current_user_stats_query=current_user_stats_query,
            beatmap_personal_best_rank_query=beatmap_personal_best_rank_query,
        )

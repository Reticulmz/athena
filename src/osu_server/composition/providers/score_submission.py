"""App-only score submission providers."""

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
    """Providers for app-only score authorization and submission processing."""

    scope = Scope.APP

    @provide
    def score_authorization_service(
        self,
        user_repo: UserQueryRepository,
        password_service: PasswordService,
        session_store: SessionStore,
    ) -> ScoreAuthorizationService:
        return ScoreAuthorizationService(
            user_repo=user_repo,
            password_service=password_service,
            session_store=session_store,
        )

    @provide
    def submit_score_use_case(self, uow_factory: UnitOfWorkFactory) -> SubmitScoreUseCase:
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

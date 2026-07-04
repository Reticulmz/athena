"""Stable web legacy transport providers."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
from osu_server.services.commands.identity import RegisterUserCommandUseCase
from osu_server.services.commands.scores import ProcessScoreSubmissionUseCase
from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService
from osu_server.services.queries.identity import (
    GetFriendEligibleUserIdsQuery,
    PermissionService,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.scores import (
    BeatmapLeaderboardQuery,
    BeatmapScoreListingQuery,
    CurrentUserStatsQuery,
    ReplayDownloadQuery,
)
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.mappers import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
    ReplayDownloadQueryParser,
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.replay_download import ReplayDownloadHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    BeatmapLeaderboardQueryRepository,
    BeatmapLeaderboardQuery,
    BeatmapMirrorService,
    BeatmapScoreListingQueryRepository,
    BeatmapScoreListingQuery,
    GetFriendEligibleUserIdsQuery,
    PermissionService,
    ProcessScoreSubmissionUseCase,
    CurrentUserStatsQuery,
    LocalEventBus,
    RegisterUserCommandUseCase,
    RequestBeatmapFileWarmupUseCase,
    ReplayDownloadQuery,
    ReplayDownloadQueryParser,
    ReplayDownloadHandler,
    SessionCredentialsQueryUseCase,
    UserQueryRepository,
)


@final
class StableWebLegacyProviderSet(Provider):
    """Providers for stable legacy web handlers, parsers, and mappers."""

    scope = Scope.APP

    @provide
    def registration_handler(
        self,
        register_user_command: RegisterUserCommandUseCase,
    ) -> RegistrationHandler:
        return RegistrationHandler(register_user_command=register_user_command)

    @provide
    def getscores_parser(self) -> GetscoresQueryParser:
        return GetscoresQueryParser()

    @provide
    def getscores_status_mapper(self) -> GetscoresStatusMapper:
        return GetscoresStatusMapper()

    @provide
    def replay_download_parser(self) -> ReplayDownloadQueryParser:
        return ReplayDownloadQueryParser()

    @provide
    def getscores_handler(
        self,
        auth_query: SessionCredentialsQueryUseCase,
        getscores_parser: GetscoresQueryParser,
        getscores_repository: BeatmapScoreListingQueryRepository,
        leaderboards: BeatmapLeaderboardQueryRepository,
        user_repository: UserQueryRepository,
        permission_service: PermissionService,
        friend_eligible_user_ids_query: GetFriendEligibleUserIdsQuery,
        status_mapper: GetscoresStatusMapper,
        beatmap_resolver: BeatmapMirrorService,
        beatmap_file_warmup: RequestBeatmapFileWarmupUseCase,
        config: AppConfig,
    ) -> GetscoresHandler:
        leaderboard_query = BeatmapLeaderboardQuery(
            getscores_repository,
            leaderboards,
            user_repository=user_repository,
            permission_service=permission_service,
            friend_eligible_user_ids_query=friend_eligible_user_ids_query,
        )
        getscores_query = BeatmapScoreListingQuery(leaderboard_query)
        return GetscoresHandler(
            auth_query=auth_query,
            getscores_parser=getscores_parser,
            getscores_query=getscores_query,
            status_mapper=status_mapper,
            beatmap_resolver=beatmap_resolver,
            beatmap_file_warmup=beatmap_file_warmup,
            beatmap_metadata_wait_seconds=config.beatmap_default_bounded_wait_seconds,
        )

    @provide
    def stable_score_submit_mapper(self, config: AppConfig) -> StableScoreSubmitMapper:
        return StableScoreSubmitMapper(
            limits=MultipartLimits(
                total_body_size=config.max_request_body_size,
                replay_size=config.score_submit_max_replay_size,
                text_field_size=config.score_submit_max_text_field_size,
            ),
            stable_web_base_url=_stable_web_base_url(config.domain),
        )

    @provide
    def score_submit_handler(
        self,
        submit_score_command: ProcessScoreSubmissionUseCase,
        mapper: StableScoreSubmitMapper,
        current_user_stats_query: CurrentUserStatsQuery,
        event_bus: LocalEventBus,
    ) -> ScoreSubmitHandler:
        return ScoreSubmitHandler(
            submit_score_command=submit_score_command,
            mapper=mapper,
            current_user_stats_query=current_user_stats_query,
            event_bus=event_bus,
        )

    @provide
    def replay_download_handler(
        self,
        auth_query: SessionCredentialsQueryUseCase,
        replay_download_parser: ReplayDownloadQueryParser,
        replay_download_query: ReplayDownloadQuery,
    ) -> ReplayDownloadHandler:
        return ReplayDownloadHandler(
            auth_query=auth_query,
            replay_download_parser=replay_download_parser,
            replay_download_query=replay_download_query,
        )


def _stable_web_base_url(domain: str) -> str:
    return f"https://osu.{domain.strip('.')}"

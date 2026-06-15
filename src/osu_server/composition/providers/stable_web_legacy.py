"""Stable web legacy transport providers."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits
from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
from osu_server.services.commands.identity import RegisterUserCommandUseCase
from osu_server.services.commands.scores import ProcessScoreSubmissionUseCase
from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService
from osu_server.services.queries.identity import SessionCredentialsQueryUseCase
from osu_server.services.queries.scores import BeatmapScoreListingQuery
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.mappers import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    BeatmapMirrorService,
    BeatmapScoreListingQuery,
    ProcessScoreSubmissionUseCase,
    RegisterUserCommandUseCase,
    SessionCredentialsQueryUseCase,
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
    def getscores_handler(
        self,
        auth_query: SessionCredentialsQueryUseCase,
        getscores_parser: GetscoresQueryParser,
        getscores_query: BeatmapScoreListingQuery,
        status_mapper: GetscoresStatusMapper,
        beatmap_resolver: BeatmapMirrorService,
        config: AppConfig,
    ) -> GetscoresHandler:
        return GetscoresHandler(
            auth_query=auth_query,
            getscores_parser=getscores_parser,
            getscores_query=getscores_query,
            status_mapper=status_mapper,
            beatmap_resolver=beatmap_resolver,
            beatmap_file_warmup=RequestBeatmapFileWarmupUseCase(beatmap_resolver),
            beatmap_metadata_wait_seconds=config.beatmap_default_bounded_wait_seconds,
        )

    @provide
    def stable_score_submit_mapper(self, config: AppConfig) -> StableScoreSubmitMapper:
        return StableScoreSubmitMapper(
            limits=MultipartLimits(
                total_body_size=config.max_request_body_size,
                replay_size=config.score_submit_max_replay_size,
                text_field_size=config.score_submit_max_text_field_size,
            )
        )

    @provide
    def score_submit_handler(
        self,
        submit_score_command: ProcessScoreSubmissionUseCase,
        mapper: StableScoreSubmitMapper,
    ) -> ScoreSubmitHandler:
        return ScoreSubmitHandler(
            submit_score_command=submit_score_command,
            mapper=mapper,
        )

"""App-only score submission providers."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.scores import ProcessScoreSubmissionUseCase, SubmitScoreUseCase
from osu_server.services.commands.scores.authorization import ScoreAuthorizationService
from osu_server.services.commands.storage.blob_storage import BlobStorageService
from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.transports.stable.web_legacy.mappers import StableScorePayloadParser

_DISHKA_RUNTIME_HINTS = (
    BeatmapMirrorService,
    BlobStorageService,
    PasswordService,
    ScoreCryptoService,
    SessionStore,
    StableScorePayloadParser,
    SubmitScoreUseCase,
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
    def stable_score_payload_parser(self) -> StableScorePayloadParser:
        return StableScorePayloadParser()

    @provide
    def process_score_submission_use_case(
        self,
        submit_score_use_case: SubmitScoreUseCase,
        replay_blob_storage: BlobStorageService,
        payload_decryptor: ScoreCryptoService,
        payload_parser: StableScorePayloadParser,
        auth_service: ScoreAuthorizationService,
        beatmap_resolver: BeatmapMirrorService,
    ) -> ProcessScoreSubmissionUseCase:
        return ProcessScoreSubmissionUseCase(
            submit_score_use_case=submit_score_use_case,
            replay_blob_storage=replay_blob_storage,
            payload_decryptor=payload_decryptor,
            payload_parser=payload_parser,
            auth_service=auth_service,
            beatmap_resolver=beatmap_resolver,
        )

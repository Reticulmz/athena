"""Unit tests for ProcessScoreSubmissionUseCase."""

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast, final, override

import pytest
import structlog.testing

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.decryption import DecryptedPayload
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.domain.scores.submission import ScoreSubmission
from osu_server.domain.storage.blobs import BlobStored
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.beatmaps.file_warmup import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
    RequestBeatmapFileWarmupUseCase,
)
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
    generate_submission_fingerprint,
    generate_submission_request_hash,
)
from osu_server.services.commands.scores.performance import (
    RequestPerformanceCalculationCommand,
    RequestPerformanceCalculationOutcome,
    RequestPerformanceCalculationResult,
)
from tests.support.fakes import (
    ScoreRepositoryViews,
    StubBlobStorageService,
    StubScorePayloadDecryptor,
    StubScorePayloadParser,
    make_score_authorization_service,
    make_score_repository_views,
    make_submit_score_use_case,
)


def _eligible_beatmap() -> BeatmapEligibility:
    return BeatmapEligibility(
        accepts_scores=True,
        has_leaderboard=True,
        awards_ranked_pp=True,
        awards_loved_pp=False,
        requires_osu_file_for_pp=True,
        is_officially_verified=True,
        is_mirror_derived=False,
        accepts_failed_scores=True,
        failed_scores_have_leaderboard=False,
        failed_scores_update_best_score=False,
        failed_scores_award_ranked_pp=False,
        failed_scores_award_loved_pp=False,
        denial_reason=None,
    )


def _ineligible_beatmap(reason: str = "status_not_eligible") -> BeatmapEligibility:
    return BeatmapEligibility(
        accepts_scores=False,
        has_leaderboard=False,
        awards_ranked_pp=False,
        awards_loved_pp=False,
        requires_osu_file_for_pp=False,
        is_officially_verified=True,
        is_mirror_derived=False,
        accepts_failed_scores=False,
        failed_scores_have_leaderboard=False,
        failed_scores_update_best_score=False,
        failed_scores_award_ranked_pp=False,
        failed_scores_award_loved_pp=False,
        denial_reason=reason,
    )


def _resolved_beatmap() -> Beatmap:
    return Beatmap(
        id=1,
        beatmapset_id=10,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode="osu",
        version="Test",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )


@dataclass(slots=True)
class FakeBeatmapResolver:
    eligibility: BeatmapEligibility | None = None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del beatmap_id, options
        return BeatmapResolveResult(
            beatmap=None,
            beatmapset=None,
            eligibility=self.eligibility,
            metadata_status=BeatmapFetchState.FRESH,
            file_status=BeatmapFileState.MISSING,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=None,
        )

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del checksum_md5, options
        return BeatmapResolveResult(
            beatmap=_resolved_beatmap(),
            beatmapset=None,
            eligibility=self.eligibility,
            metadata_status=BeatmapFetchState.FRESH,
            file_status=BeatmapFileState.MISSING,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=None,
        )


class RecordingWarmupUseCase:
    def __init__(
        self,
        events: list[str],
        *,
        outcome: BeatmapFileWarmupOutcome = BeatmapFileWarmupOutcome.REQUESTED,
    ) -> None:
        self.events: list[str] = events
        self.outcome: BeatmapFileWarmupOutcome = outcome
        self.requests: list[BeatmapFileWarmupRequest] = []

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
        self.events.append("warmup")
        self.requests.append(request)
        return BeatmapFileWarmupResult(
            outcome=self.outcome,
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=request.beatmap_id,
            checksum_md5=request.checksum_md5,
            reason=None,
        )


@final
class RecordingPerformanceCalculationRequest:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.commands: list[RequestPerformanceCalculationCommand] = []

    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult:
        self.commands.append(command)
        if self._fail:
            msg = "performance request failed"
            raise RuntimeError(msg)
        return RequestPerformanceCalculationResult(
            outcome=RequestPerformanceCalculationOutcome.SCORE_NOT_FOUND,
            score_id=command.score_id,
        )


@final
class StubPerformanceCalculatorIdentity:
    def calculator_name(self) -> str:
        return "test-calculator"

    def calculator_version(self) -> str:
        return "1.2.3"


@dataclass(slots=True)
class FakeWarmupResolver:
    file_status: BeatmapFileState
    reason: str | None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del options
        return self._result(beatmap_id)

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        del checksum_md5, options
        return self._result(1)

    def _result(self, beatmap_id: int) -> BeatmapResolveResult:
        beatmap = replace(_resolved_beatmap(), id=beatmap_id, file_state=self.file_status)
        return BeatmapResolveResult(
            beatmap=beatmap,
            beatmapset=None,
            eligibility=_eligible_beatmap(),
            metadata_status=BeatmapFetchState.FRESH,
            file_status=self.file_status,
            source=BeatmapMetadataSource.OFFICIAL,
            verified=True,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=self.reason,
        )


class RecordingBlobStorageService(StubBlobStorageService):
    def __init__(self, events: list[str], *, fail_writes: bool = False) -> None:
        super().__init__(fail_writes=fail_writes)
        self.events: list[str] = events

    @override
    async def put_bytes(self, data: bytes, *, content_type: str) -> BlobStored:
        self.events.append("blob_storage")
        return await super().put_bytes(data, content_type=content_type)


@pytest.fixture
def uow_factory() -> InMemoryUnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory()


@pytest.fixture
def repos(uow_factory: InMemoryUnitOfWorkFactory) -> ScoreRepositoryViews:
    """Create in-memory repositories."""
    return make_score_repository_views(uow_factory)


@pytest.fixture
def beatmap_resolver() -> FakeBeatmapResolver:
    return FakeBeatmapResolver(_eligible_beatmap())


@pytest.fixture
def blob_storage() -> StubBlobStorageService:
    return StubBlobStorageService()


@pytest.fixture
def score_decryptor() -> StubScorePayloadDecryptor:
    return StubScorePayloadDecryptor()


@pytest.fixture
def service(
    uow_factory: InMemoryUnitOfWorkFactory,
    beatmap_resolver: FakeBeatmapResolver,
    blob_storage: StubBlobStorageService,
    score_decryptor: StubScorePayloadDecryptor,
) -> ProcessScoreSubmissionUseCase:
    """Create service with in-memory repositories."""
    auth_service = make_score_authorization_service()
    return ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        blob_storage,
        score_decryptor,
        StubScorePayloadParser(),
        auth_service,
        beatmap_resolver,
    )


@pytest.fixture
def valid_payload() -> bytes:
    """Valid encrypted score payload (mock)."""
    return b"encrypted_data"


@pytest.fixture
def valid_input(valid_payload: bytes) -> ParsedSubmissionInput:
    """Valid submission input."""
    return ParsedSubmissionInput(
        encrypted_payload=valid_payload,
        iv=b"0" * 32,
        replay_data=b"replay_binary_data",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # "password"
        client_hash="test_hash",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,  # Ranked in mock
        submitted_at=datetime.now(UTC),
    )


def _fingerprint_for(
    input_data: ParsedSubmissionInput,
    *,
    beatmap_checksum: str = "abc123",
    user_id: int = 1000,
    submitted_timestamp: str | None = None,
) -> str:
    return generate_submission_fingerprint(
        user_id=user_id,
        beatmap_checksum=beatmap_checksum,
        submitted_timestamp=submitted_timestamp,
        request_hash=generate_submission_request_hash(input_data),
    )


@pytest.mark.asyncio
async def test_happy_path_valid_submission_creates_score(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Happy path: valid submission creates score record."""
    score_repo, submission_repo, _replay_repo = repos

    # Mock decrypt
    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_1:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert result.error_reason is None

    # Verify score persisted
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.user_id == 1000
    assert score.passed is True
    assert score.ruleset == Ruleset.OSU
    assert score.playstyle == Playstyle.VANILLA
    assert score.beatmap_status_at_submission == BeatmapRankStatus.RANKED.value

    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(valid_input))
    assert submission is not None
    assert submission.result_snapshot is not None
    assert (
        submission.result_snapshot["beatmap_status_at_submission"]
        == BeatmapRankStatus.RANKED.value
    )


@pytest.mark.asyncio
async def test_completed_submission_requests_performance_calculation(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Accepted score persistence is followed by a durable performance request."""
    score_repo, _submission_repo, _replay_repo = repos
    performance_request = RecordingPerformanceCalculationRequest()
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=performance_request,
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:online_checksum_perf_request:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert await score_repo.get_by_id(result.score_id) is not None
    assert performance_request.commands == [
        RequestPerformanceCalculationCommand(
            score_id=result.score_id,
            calculator_name="test-calculator",
            calculator_version="1.2.3",
            requested_at=valid_input.submitted_at,
        )
    ]


@pytest.mark.asyncio
async def test_performance_calculation_request_failure_keeps_completed_response(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Worker wake/request diagnostics do not reject an accepted stable submission."""
    performance_request = RecordingPerformanceCalculationRequest(fail=True)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        performance_calculation_request=performance_request,
        performance_calculator_identity=StubPerformanceCalculatorIdentity(),
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:online_checksum_perf_failure:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    with structlog.testing.capture_logs() as logs:
        result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert len(performance_request.commands) == 1
    entries = [
        entry for entry in logs if entry["event"] == "score_performance_calculation_request_failed"
    ]
    assert len(entries) == 1
    assert entries[0]["score_id"] == result.score_id
    assert entries[0]["error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_client_server_grade_discrepancy_is_preserved(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Client/server grade mismatches are logged and stored for diagnostics."""
    _score_repo, submission_repo, _replay_repo = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "abc123:test_user:online_grade_discrepancy:"
            "300:0:0:0:0:0:1000000:500:1:D:0:1:0:"
            "20240101:b20240101:client_checksum"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    with structlog.testing.capture_logs() as cap_logs:
        result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    submission = await submission_repo.get_by_fingerprint(
        _fingerprint_for(valid_input, submitted_timestamp="20240101")
    )
    assert submission is not None
    assert submission.result_snapshot is not None
    assert submission.result_snapshot["grade_discrepancy"] == {
        "client_grade": "D",
        "server_grade": "X",
    }

    discrepancy_log = next(
        entry for entry in cap_logs if entry["event"] == "score_grade_discrepancy"
    )
    assert discrepancy_log["client_grade"] == "D"
    assert discrepancy_log["server_grade"] == "X"


@pytest.mark.asyncio
async def test_crypto_checksum_invalid_is_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Crypto checksum mismatch is rejected before parsing or persistence."""
    score_repo, _, _ = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:online_checksum_bad_crypto:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=False)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason == "crypto_checksum_invalid"
    assert not await score_repo.exists_by_online_checksum("online_checksum_bad_crypto")


@pytest.mark.asyncio
async def test_failed_play_handling(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Failed play (passed=0) is stored."""
    score_repo, _, _ = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        # passed=0 (last field)
        payload = "1000:test_user:abc123:online_checksum_2:0:0:50:10:5:0:0:10:200000:40:0:0"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False


@pytest.mark.asyncio
async def test_failed_play_without_replay_is_accepted_without_blob_write(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    blob_storage: StubBlobStorageService,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Failed play can be stored without replay data."""
    score_repo, _, _ = repos
    input_without_replay = replace(valid_input, replay_data=None, fail_time_ms=42_000)

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:online_checksum_failed_no_replay:"
            "0:0:50:10:5:0:0:10:200000:40:0:0"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(input_without_replay)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False
    assert blob_storage.writes == []


@pytest.mark.asyncio
async def test_passed_play_without_replay_is_accepted_without_blob_write(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    blob_storage: StubBlobStorageService,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Passed play without replay data creates a score without an attachment."""
    score_repo, _, _ = repos
    input_without_replay = replace(valid_input, replay_data=None)

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:online_checksum_passed_no_replay:"
            "0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(input_without_replay)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert await score_repo.exists_by_online_checksum("online_checksum_passed_no_replay")
    assert blob_storage.writes == []


@pytest.mark.asyncio
async def test_replay_attachment(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    blob_storage: StubBlobStorageService,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Replay data is attached to score."""
    _, _, replay_repo = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_3:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify replay exists
    assert valid_input.replay_data is not None
    replay_checksum = hashlib.sha256(valid_input.replay_data).hexdigest()
    assert await replay_repo.exists_by_checksum(replay_checksum)
    assert blob_storage.writes == [valid_input.replay_data]
    assert blob_storage.stored[0].sha256 == replay_checksum


@pytest.mark.asyncio
async def test_score_submit_fallback_warmup_runs_before_replay_blob_storage(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Accepted submissions ignore warmup result and warm before replay storage."""
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events, outcome=BeatmapFileWarmupOutcome.FAILED)
    blob_storage = RecordingBlobStorageService(events)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        blob_storage,
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_warmup:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    input_data = replace(valid_input, beatmap_id=42)
    result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.beatmap_id == 42
    assert events == ["warmup", "blob_storage"]
    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
            user_id=1000,
            beatmap_id=42,
            checksum_md5="abc123",
        )
    ]


@pytest.mark.asyncio
async def test_score_submit_accepts_file_pending_and_logs_fallback_warmup(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Beatmap File pending is diagnostics-only and keeps accepted response shape."""
    warmup = RequestBeatmapFileWarmupUseCase(
        FakeWarmupResolver(
            file_status=BeatmapFileState.PENDING_FETCH,
            reason="pending_fetch",
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:online_checksum_warmup_pending:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    with structlog.testing.capture_logs() as logs:
        result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.error_reason is None
    assert result.score_id is not None
    assert result.beatmap_id == 1

    warmup_events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert len(warmup_events) == 1
    warmup_event = warmup_events[0]
    assert warmup_event["entrance"] == "stable_score_submit_fallback"
    assert warmup_event["outcome"] == "requested"
    assert warmup_event["beatmap_id"] == 1
    assert warmup_event["checksum_md5"] is None
    assert warmup_event["reason"] == "pending_fetch"


@pytest.mark.asyncio
async def test_score_submit_fallback_warmup_precedes_retryable_replay_storage_failure(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Replay storage retryable failures happen after fallback warmup is requested."""
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events)
    blob_storage = RecordingBlobStorageService(events, fail_writes=True)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        blob_storage,
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:online_checksum_warmup_retry:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.RETRYABLE
    assert result.error_reason == "replay_blob_store_failed"
    assert events == ["warmup", "blob_storage"]
    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
            user_id=1000,
            beatmap_id=1,
            checksum_md5="abc123",
        )
    ]


@pytest.mark.asyncio
async def test_score_submit_terminal_reject_does_not_request_fallback_warmup(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Terminal rejects before hit validation do not trigger score submit fallback warmup."""
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:online_checksum_warmup_reject:0:0:0:0:0:0:0:0:500000:0:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "validation_failed" in result.error_reason
    assert events == []
    assert warmup.requests == []


@pytest.mark.asyncio
async def test_online_checksum_duplicate_rejection(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Duplicate online checksum rejects a different submission."""
    _score_repo, submission_repo, _ = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:duplicate_checksum:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    # First submission
    result1 = await service.execute(valid_input)
    assert result1.outcome == SubmissionOutcome.COMPLETED

    # Second submission (different fingerprint but same online checksum)
    input2 = ParsedSubmissionInput(
        encrypted_payload=valid_input.encrypted_payload,
        iv=valid_input.iv,
        replay_data=valid_input.replay_data,
        password_md5=valid_input.password_md5,
        client_hash="different_hash",  # Different hash = different fingerprint
        fail_time_ms=valid_input.fail_time_ms,
        osu_version=valid_input.osu_version,
        beatmap_id=valid_input.beatmap_id,
        submitted_at=datetime.now(UTC),  # Different timestamp
    )
    result2 = await service.execute(input2)
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_online_checksum"
    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_online_checksum"}


@pytest.mark.asyncio
async def test_online_checksum_duplicate_rejection_ignores_fallback_warmup_failure(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Duplicate online checksum remains a terminal reject when warmup fails."""
    _score_repo, submission_repo, _ = repos
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events, outcome=BeatmapFileWarmupOutcome.FAILED)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:duplicate_checksum_with_warmup:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)
    input1 = replace(valid_input, replay_data=b"online_duplicate_replay_1", client_hash="hash1")
    input2 = replace(valid_input, replay_data=b"online_duplicate_replay_2", client_hash="hash2")

    result1 = await service.execute(input1)
    result2 = await service.execute(input2)

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_online_checksum"
    assert len(warmup.requests) == 2
    assert events == ["warmup", "warmup"]

    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_online_checksum"}


@pytest.mark.asyncio
async def test_online_checksum_duplicate_rejection_ignores_file_pending_warmup(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Duplicate online checksum remains terminal rejected when file warmup is pending."""
    _score_repo, submission_repo, _ = repos
    warmup = RequestBeatmapFileWarmupUseCase(
        FakeWarmupResolver(
            file_status=BeatmapFileState.PENDING_FETCH,
            reason="pending_fetch",
        )
    )
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = (
            "1000:test_user:abc123:duplicate_checksum_pending_warmup:0:0:100:10:5:0:0:2:"
            "500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)
    input1 = replace(valid_input, replay_data=b"online_pending_replay_1", client_hash="hash1")
    input2 = replace(valid_input, replay_data=b"online_pending_replay_2", client_hash="hash2")

    with structlog.testing.capture_logs() as logs:
        result1 = await service.execute(input1)
        result2 = await service.execute(input2)

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_online_checksum"

    warmup_events = [entry for entry in logs if entry["event"] == "beatmap_file_warmup"]
    assert [entry["outcome"] for entry in warmup_events] == ["requested", "requested"]
    assert [entry["reason"] for entry in warmup_events] == ["pending_fetch", "pending_fetch"]

    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_online_checksum"}


@pytest.mark.asyncio
async def test_replay_checksum_duplicate_rejection(
    service: ProcessScoreSubmissionUseCase,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Duplicate replay checksum is rejected."""
    _, _, _replay_repo = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        # Different online checksums
        if b"first" in _encrypted:
            payload = "1000:test_user:abc123:online_1:0:0:100:10:5:0:0:2:500000:99:1:1"
        else:
            payload = "1000:test_user:abc123:online_2:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    # First submission
    input1 = ParsedSubmissionInput(
        encrypted_payload=b"first",
        iv=b"0" * 32,
        replay_data=b"same_replay_data",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="hash1",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )
    result1 = await service.execute(input1)
    assert result1.outcome == SubmissionOutcome.COMPLETED

    # Second submission (same replay)
    input2 = ParsedSubmissionInput(
        encrypted_payload=b"second",
        iv=b"0" * 32,
        replay_data=b"same_replay_data",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="hash2",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )
    result2 = await service.execute(input2)
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.error_reason is not None
    assert "duplicate_replay_checksum" in result2.error_reason


@pytest.mark.asyncio
async def test_replay_checksum_duplicate_rejection_ignores_fallback_warmup_failure(
    uow_factory: InMemoryUnitOfWorkFactory,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Duplicate replay checksum remains a terminal reject when warmup fails."""
    _score_repo, submission_repo, _replay_repo = repos
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events, outcome=BeatmapFileWarmupOutcome.FAILED)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        if b"first" in _encrypted:
            payload = (
                "1000:test_user:abc123:online_warmup_replay_1:0:0:100:10:5:0:0:2:500000:99:1:1"
            )
        else:
            payload = (
                "1000:test_user:abc123:online_warmup_replay_2:0:0:100:10:5:0:0:2:500000:99:1:1"
            )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)
    input1 = ParsedSubmissionInput(
        encrypted_payload=b"first",
        iv=b"0" * 32,
        replay_data=b"same_warmup_replay_data",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="hash1",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )
    input2 = ParsedSubmissionInput(
        encrypted_payload=b"second",
        iv=b"0" * 32,
        replay_data=b"same_warmup_replay_data",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        client_hash="hash2",
        fail_time_ms=None,
        osu_version="20240101",
        beatmap_id=1,
        submitted_at=datetime.now(UTC),
    )

    result1 = await service.execute(input1)
    result2 = await service.execute(input2)

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_replay_checksum"
    assert len(warmup.requests) == 2
    assert events == ["warmup", "warmup"]

    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_replay_checksum"}


@pytest.mark.asyncio
async def test_submission_fingerprint_idempotency(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Same request content returns cached persisted result."""
    decrypt_call_count = 0

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        nonlocal decrypt_call_count
        decrypt_call_count += 1
        payload = "1000:test_user:abc123:online_checksum_idem:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    # First submission
    result1 = await service.execute(valid_input)
    assert result1.outcome == SubmissionOutcome.COMPLETED
    score_id1 = result1.score_id

    resent_input = replace(valid_input, submitted_at=datetime.now(UTC))

    # Second submission has a different server receive time but identical request content.
    result2 = await service.execute(resent_input)
    assert result2.outcome == SubmissionOutcome.COMPLETED
    assert result2.score_id == score_id1  # Same score ID
    assert decrypt_call_count == 2


@pytest.mark.asyncio
async def test_submission_fingerprint_idempotency_ignores_fallback_warmup_failure(
    uow_factory: InMemoryUnitOfWorkFactory,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
    beatmap_resolver: FakeBeatmapResolver,
) -> None:
    """Same-fingerprint cached result is unchanged by fallback warmup failure."""
    events: list[str] = []
    warmup = RecordingWarmupUseCase(events, outcome=BeatmapFileWarmupOutcome.FAILED)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        score_decryptor,
        StubScorePayloadParser(),
        make_score_authorization_service(),
        beatmap_resolver,
        beatmap_file_warmup_use_case=warmup,
    )
    decrypt_call_count = 0

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        nonlocal decrypt_call_count
        decrypt_call_count += 1
        payload = (
            "1000:test_user:abc123:online_checksum_idem_warmup:0:0:100:10:5:0:0:2:500000:99:1:1"
        )
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)
    replayless_input = replace(valid_input, replay_data=None)

    result1 = await service.execute(replayless_input)
    result2 = await service.execute(replace(replayless_input, submitted_at=datetime.now(UTC)))

    assert result1.outcome == SubmissionOutcome.COMPLETED
    assert result1.score_id is not None
    assert result2.outcome == SubmissionOutcome.COMPLETED
    assert result2.error_reason is None
    assert result2.score_id == result1.score_id
    assert len(warmup.requests) == 2
    assert events == ["warmup", "warmup"]
    assert decrypt_call_count == 2


@pytest.mark.asyncio
async def test_in_progress_retry_returns_accepted_pending(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepositoryViews,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Same fingerprint in processing state returns accepted_pending."""
    _score_repo, submission_repo, _replay_repo = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_pending:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)
    fingerprint = _fingerprint_for(valid_input)
    _ = await submission_repo.create(
        ScoreSubmission(
            id=None,
            fingerprint=fingerprint,
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=valid_input.submitted_at,
            state="processing",
            result_snapshot=None,
        )
    )

    result = await service.execute(valid_input)

    assert result.outcome == SubmissionOutcome.ACCEPTED_PENDING
    assert result.error_reason == "accepted_pending"


@pytest.mark.asyncio
async def test_authorization_failure_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Authorization failure returns terminal reject."""

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_auth:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    # Invalid password
    invalid_input = ParsedSubmissionInput(
        encrypted_payload=valid_input.encrypted_payload,
        iv=valid_input.iv,
        replay_data=valid_input.replay_data,
        password_md5="invalid_md5",
        client_hash=valid_input.client_hash,
        fail_time_ms=valid_input.fail_time_ms,
        osu_version=valid_input.osu_version,
        beatmap_id=valid_input.beatmap_id,
        submitted_at=valid_input.submitted_at,
    )

    result = await service.execute(invalid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "authorization_failed" in result.error_reason


@pytest.mark.asyncio
async def test_beatmap_ineligibility_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Ineligible beatmap returns terminal reject."""

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_elig:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    beatmap_resolver.eligibility = _ineligible_beatmap()

    result = await service.execute(valid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "beatmap_ineligible" in result.error_reason


@pytest.mark.asyncio
async def test_validation_failure_terminal_reject(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Validation failure returns terminal reject."""

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        # Invalid: total_hits=0
        payload = "1000:test_user:abc123:online_checksum_val:0:0:0:0:0:0:0:0:500000:0:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.execute(valid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "validation_failed" in result.error_reason


@pytest.mark.asyncio
async def test_metrics_logged_on_success(
    service: ProcessScoreSubmissionUseCase,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Metrics are logged on successful submission."""

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_metrics:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    with structlog.testing.capture_logs() as cap_logs:
        result = await service.execute(valid_input)
    assert result.outcome == SubmissionOutcome.COMPLETED

    logged_metrics = next(
        entry for entry in cap_logs if entry["event"] == "score_submission_completed"
    )
    duration_ms = cast("object", logged_metrics["duration_ms"])
    decrypt_latency_ms = cast("object", logged_metrics["decrypt_latency_ms"])
    beatmap_latency_ms = cast("object", logged_metrics["beatmap_latency_ms"])
    db_latency_ms = cast("object", logged_metrics["db_latency_ms"])
    assert isinstance(duration_ms, float)
    assert isinstance(decrypt_latency_ms, float)
    assert isinstance(beatmap_latency_ms, float)
    assert isinstance(db_latency_ms, float)

    assert duration_ms > 0
    assert decrypt_latency_ms >= 0
    assert beatmap_latency_ms >= 0
    assert db_latency_ms > 0

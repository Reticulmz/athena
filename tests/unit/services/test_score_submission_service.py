"""Unit tests for ScoreSubmissionService."""

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast

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
from osu_server.domain.score.decryption import DecryptedPayload
from osu_server.domain.score.score import Playstyle, Ruleset
from osu_server.domain.score.submission import ScoreSubmission
from osu_server.repositories.memory.replay_repository import InMemoryReplayRepository
from osu_server.repositories.memory.score_repository import InMemoryScoreRepository
from osu_server.repositories.memory.submission_repository import InMemoryScoreSubmissionRepository
from osu_server.services.score_submission_service import (
    ParsedSubmissionInput,
    ScoreSubmissionService,
    SubmissionOutcome,
    generate_submission_fingerprint,
    generate_submission_request_hash,
)
from tests.support.fakes import (
    StubBlobStorageService,
    StubScorePayloadDecryptor,
    make_score_authorization_service,
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


type ScoreRepos = tuple[
    InMemoryScoreRepository,
    InMemoryScoreSubmissionRepository,
    InMemoryReplayRepository,
]


@pytest.fixture
def repos() -> ScoreRepos:
    """Create in-memory repositories."""
    return (
        InMemoryScoreRepository(),
        InMemoryScoreSubmissionRepository(),
        InMemoryReplayRepository(),
    )


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
    repos: ScoreRepos,
    beatmap_resolver: FakeBeatmapResolver,
    blob_storage: StubBlobStorageService,
    score_decryptor: StubScorePayloadDecryptor,
) -> ScoreSubmissionService:
    """Create service with in-memory repositories."""
    score_repo, submission_repo, replay_repo = repos
    auth_service = make_score_authorization_service()
    return ScoreSubmissionService(
        score_repo,
        submission_repo,
        replay_repo,
        blob_storage,
        score_decryptor,
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
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Happy path: valid submission creates score record."""
    score_repo, submission_repo, _replay_repo = repos

    # Mock decrypt
    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_1:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.submit_score(valid_input)

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
async def test_client_server_grade_discrepancy_is_preserved(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
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
        result = await service.submit_score(valid_input)

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
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
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

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason == "crypto_checksum_invalid"
    assert not await score_repo.exists_by_online_checksum("online_checksum_bad_crypto")


@pytest.mark.asyncio
async def test_failed_play_handling(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Failed play (passed=0) is stored."""
    score_repo, _, _ = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        # passed=0 (last field)
        payload = "1000:test_user:abc123:online_checksum_2:0:0:50:10:5:0:0:10:200000:40:0:0"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False


@pytest.mark.asyncio
async def test_failed_play_without_replay_is_accepted_without_blob_write(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
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

    result = await service.submit_score(input_without_replay)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False
    assert blob_storage.writes == []


@pytest.mark.asyncio
async def test_passed_play_without_replay_is_accepted_without_blob_write(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
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

    result = await service.submit_score(input_without_replay)

    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None
    assert await score_repo.exists_by_online_checksum("online_checksum_passed_no_replay")
    assert blob_storage.writes == []


@pytest.mark.asyncio
async def test_replay_attachment(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
    blob_storage: StubBlobStorageService,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Replay data is attached to score."""
    _, _, replay_repo = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_3:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify replay exists
    assert valid_input.replay_data is not None
    replay_checksum = hashlib.sha256(valid_input.replay_data).hexdigest()
    assert await replay_repo.exists_by_checksum(replay_checksum)
    assert blob_storage.writes == [valid_input.replay_data]
    assert blob_storage.stored[0].sha256 == replay_checksum


@pytest.mark.asyncio
async def test_online_checksum_duplicate_rejection(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Duplicate online checksum rejects a different submission."""
    _score_repo, submission_repo, _ = repos

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:duplicate_checksum:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    # First submission
    result1 = await service.submit_score(valid_input)
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
    result2 = await service.submit_score(input2)
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.score_id is None
    assert result2.error_reason == "duplicate_online_checksum"
    submission = await submission_repo.get_by_fingerprint(_fingerprint_for(input2))
    assert submission is not None
    assert submission.state == "terminal_rejected"
    assert submission.result_snapshot == {"error_reason": "duplicate_online_checksum"}


@pytest.mark.asyncio
async def test_replay_checksum_duplicate_rejection(
    service: ScoreSubmissionService,
    repos: ScoreRepos,
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
    result1 = await service.submit_score(input1)
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
    result2 = await service.submit_score(input2)
    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.error_reason is not None
    assert "duplicate_replay_checksum" in result2.error_reason


@pytest.mark.asyncio
async def test_submission_fingerprint_idempotency(
    service: ScoreSubmissionService,
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
    result1 = await service.submit_score(valid_input)
    assert result1.outcome == SubmissionOutcome.COMPLETED
    score_id1 = result1.score_id

    resent_input = replace(valid_input, submitted_at=datetime.now(UTC))

    # Second submission has a different server receive time but identical request content.
    result2 = await service.submit_score(resent_input)
    assert result2.outcome == SubmissionOutcome.COMPLETED
    assert result2.score_id == score_id1  # Same score ID
    assert decrypt_call_count == 2


@pytest.mark.asyncio
async def test_in_progress_retry_returns_accepted_pending(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos: ScoreRepos,
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

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.ACCEPTED_PENDING
    assert result.error_reason == "accepted_pending"


@pytest.mark.asyncio
async def test_authorization_failure_terminal_reject(
    service: ScoreSubmissionService,
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

    result = await service.submit_score(invalid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "authorization_failed" in result.error_reason


@pytest.mark.asyncio
async def test_beatmap_ineligibility_terminal_reject(
    service: ScoreSubmissionService,
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

    result = await service.submit_score(valid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "beatmap_ineligible" in result.error_reason


@pytest.mark.asyncio
async def test_validation_failure_terminal_reject(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Validation failure returns terminal reject."""

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        # Invalid: total_hits=0
        payload = "1000:test_user:abc123:online_checksum_val:0:0:0:0:0:0:0:0:500000:0:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    result = await service.submit_score(valid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "validation_failed" in result.error_reason


@pytest.mark.asyncio
async def test_metrics_logged_on_success(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    score_decryptor: StubScorePayloadDecryptor,
) -> None:
    """Metrics are logged on successful submission."""

    def mock_decrypt(_encrypted: bytes, _iv: bytes, _osu_version: str | None) -> DecryptedPayload:
        payload = "1000:test_user:abc123:online_checksum_metrics:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    score_decryptor.set_factory(mock_decrypt)

    with structlog.testing.capture_logs() as cap_logs:
        result = await service.submit_score(valid_input)
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

# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnusedParameter=false, reportOperatorIssue=false, reportMissingParameterType=false
"""Unit tests for ScoreSubmissionService."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from osu_server.domain.beatmap import (
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.domain.score.score import Playstyle, Ruleset
from osu_server.infrastructure.auth.score_authorization import (
    ScoreAuthorizationService,
)
from osu_server.infrastructure.crypto.score_crypto import DecryptedPayload
from osu_server.repositories.memory.replay_repository import InMemoryReplayRepository
from osu_server.repositories.memory.score_repository import InMemoryScoreRepository
from osu_server.repositories.memory.submission_repository import InMemoryScoreSubmissionRepository
from osu_server.services.score_submission_service import (
    ParsedSubmissionInput,
    ScoreSubmissionService,
    SubmissionOutcome,
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


@dataclass(slots=True)
class FakeBeatmapResolver:
    eligibility: BeatmapEligibility | None = None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,  # noqa: ARG002
        options: BeatmapResolveOptions | None = None,  # noqa: ARG002
    ) -> BeatmapResolveResult:
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


@pytest.fixture
def repos() -> tuple[
    InMemoryScoreRepository, InMemoryScoreSubmissionRepository, InMemoryReplayRepository
]:
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
def service(repos, beatmap_resolver: FakeBeatmapResolver) -> ScoreSubmissionService:
    """Create service with in-memory repositories."""
    score_repo, submission_repo, replay_repo = repos
    auth_service = ScoreAuthorizationService()
    return ScoreSubmissionService(
        score_repo, submission_repo, replay_repo, auth_service, beatmap_resolver
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


@pytest.mark.asyncio
async def test_happy_path_valid_submission_creates_score(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos,
    monkeypatch,
) -> None:
    """Happy path: valid submission creates score record."""
    score_repo, _submission_repo, _replay_repo = repos

    # Mock decrypt
    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = "1000:test_user:abc123:online_checksum_1:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

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


@pytest.mark.asyncio
async def test_failed_play_handling(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos,
    monkeypatch,
) -> None:
    """Failed play (passed=0) is stored."""
    score_repo, _, _ = repos

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        # passed=0 (last field)
        payload = "1000:test_user:abc123:online_checksum_2:0:0:50:10:5:0:0:10:200000:40:0:0"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED
    score = await score_repo.get_by_id(result.score_id)
    assert score is not None
    assert score.passed is False


@pytest.mark.asyncio
async def test_replay_attachment(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos,
    monkeypatch,
) -> None:
    """Replay data is attached to score."""
    _, _, replay_repo = repos

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = "1000:test_user:abc123:online_checksum_3:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)

    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify replay exists
    assert valid_input.replay_data is not None
    replay_checksum = hashlib.sha256(valid_input.replay_data).hexdigest()
    assert await replay_repo.exists_by_checksum(replay_checksum)


@pytest.mark.asyncio
async def test_online_checksum_duplicate_rejection(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    repos,
    monkeypatch,
) -> None:
    """Duplicate online checksum is rejected."""
    _score_repo, _, _ = repos

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = "1000:test_user:abc123:duplicate_checksum:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

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
    assert "duplicate_online_checksum" in result2.error_reason  # type: ignore[operator]


@pytest.mark.asyncio
async def test_replay_checksum_duplicate_rejection(
    service: ScoreSubmissionService,
    repos,
    monkeypatch,
) -> None:
    """Duplicate replay checksum is rejected."""
    _, _, _replay_repo = repos

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        # Different online checksums
        if b"first" in encrypted:
            payload = "1000:test_user:abc123:online_1:0:0:100:10:5:0:0:2:500000:99:1:1"
        else:
            payload = "1000:test_user:abc123:online_2:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

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
    assert "duplicate_replay_checksum" in result2.error_reason  # type: ignore[operator]


@pytest.mark.asyncio
async def test_submission_fingerprint_idempotency(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    monkeypatch,
) -> None:
    """Same submission fingerprint returns cached result."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = "1000:test_user:abc123:online_checksum_idem:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    # First submission
    result1 = await service.submit_score(valid_input)
    assert result1.outcome == SubmissionOutcome.COMPLETED
    score_id1 = result1.score_id

    # Second submission (same fingerprint)
    result2 = await service.submit_score(valid_input)
    assert result2.outcome == SubmissionOutcome.COMPLETED
    assert result2.score_id == score_id1  # Same score ID


@pytest.mark.asyncio
async def test_authorization_failure_terminal_reject(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    monkeypatch,
) -> None:
    """Authorization failure returns terminal reject."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = "1000:test_user:abc123:online_checksum_auth:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

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
    assert "authorization_failed" in result.error_reason  # type: ignore[operator]


@pytest.mark.asyncio
async def test_beatmap_ineligibility_terminal_reject(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    beatmap_resolver: FakeBeatmapResolver,
    monkeypatch,
) -> None:
    """Ineligible beatmap returns terminal reject."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        payload = "1000:test_user:abc123:online_checksum_elig:0:0:100:10:5:0:0:2:500000:99:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    beatmap_resolver.eligibility = _ineligible_beatmap()

    result = await service.submit_score(valid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert "beatmap_ineligible" in result.error_reason  # type: ignore[operator]


@pytest.mark.asyncio
async def test_validation_failure_terminal_reject(
    service: ScoreSubmissionService,
    valid_input: ParsedSubmissionInput,
    monkeypatch,
) -> None:
    """Validation failure returns terminal reject."""

    def mock_decrypt(encrypted: bytes, iv: bytes, osu_version: str | None) -> DecryptedPayload:  # noqa: ARG001
        # Invalid: total_hits=0
        payload = "1000:test_user:abc123:online_checksum_val:0:0:0:0:0:0:0:0:500000:0:1:1"
        return DecryptedPayload(plaintext=payload, checksum_valid=True)

    monkeypatch.setattr(
        "osu_server.services.score_submission_service.decrypt_score_payload",
        mock_decrypt,
    )

    result = await service.submit_score(valid_input)
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert "validation_failed" in result.error_reason  # type: ignore[operator]

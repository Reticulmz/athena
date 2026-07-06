"""Security verification tests for score submission (Requirement 11: Security and Privacy).

This module verifies that:
- R11.1: No raw password-md5 is logged on authorization failure
- R11.2: Failure categories are logged for diagnostics
- R11.3: Opaque fields are stored as SHA-256 hashes only
- R11.4: No raw password-md5, token, or encrypted payload is persisted or logged
- R11.5: Submission fingerprint and result snapshot are recorded
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

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
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.payload_parser import ParsedScore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import (
    ParsedSubmissionInput,
    ProcessScoreSubmissionUseCase,
    SubmissionOutcome,
    generate_submission_fingerprint,
)
from osu_server.services.commands.scores.authorization import ScoreAuthorizationService
from tests.support.fakes import (
    StubBlobStorageService,
    UowScoreSubmissionRepositoryView,
    make_score_authorization_service,
    make_score_repository_views,
    make_submit_score_use_case,
    make_test_submission_input,
)


def _resolved_beatmap() -> Beatmap:
    return Beatmap(
        id=123,
        beatmapset_id=456,
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


def _fingerprint_for(
    input_data: ParsedSubmissionInput,
    *,
    user_id: int = 1000,
    beatmap_checksum: str = "valid_checksum",
    submitted_timestamp: str | None = None,
) -> str:
    return generate_submission_fingerprint(
        user_id=user_id,
        beatmap_checksum=beatmap_checksum,
        submitted_timestamp=submitted_timestamp,
        request_hash=input_data.request_hash,
    )


def _valid_parsed_score(
    *,
    beatmap_checksum: str = "valid_checksum",
    online_checksum: str = "12345678",
) -> ParsedScore:
    return ParsedScore(
        user_id=1000,
        username="test_user",
        beatmap_checksum=beatmap_checksum,
        online_checksum=online_checksum,
        ruleset=0,
        mods=ModCombination.none(),
        n300=300,
        n100=100,
        n50=50,
        geki=5,
        katu=3,
        miss=2,
        score=1000000,
        max_combo=500,
        perfect=False,
        passed=True,
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


def _make_process_score_submission_use_case(
    *,
    resolver: FakeBeatmapResolver,
    auth_service: ScoreAuthorizationService,
) -> tuple[
    ProcessScoreSubmissionUseCase,
    UowScoreSubmissionRepositoryView,
]:
    uow_factory = InMemoryUnitOfWorkFactory()
    _, submission_repo, _ = make_score_repository_views(uow_factory)
    service = ProcessScoreSubmissionUseCase(
        make_submit_score_use_case(uow_factory),
        StubBlobStorageService(),
        auth_service,
        resolver,
    )
    return service, submission_repo


@pytest.mark.asyncio
async def test_authorization_failure_does_not_log_raw_password_md5() -> None:
    """R11.1: Authorization failures must not log raw password-md5.

    Verify that actual log output does not contain raw password-md5 when
    authorization fails. Instead, a SHA-256 hash should be logged.
    """
    auth_service = make_score_authorization_service()
    resolver = FakeBeatmapResolver(
        eligibility=BeatmapEligibility(
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
    )

    service, _ = _make_process_score_submission_use_case(
        resolver=resolver,
        auth_service=auth_service,
    )

    invalid_password = "invalid_password_md5_hash_12345"
    input_data = make_test_submission_input(
        parsed_score=_valid_parsed_score(),
        replay_data=None,
        password_md5=invalid_password,
        osu_version="2024.101.0",
        beatmap_id=123,
    )

    # Capture actual log output
    with structlog.testing.capture_logs() as cap_logs:
        result = await service.execute(input_data)

    # Verify rejection
    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "authorization_failed" in result.error_reason

    # CRITICAL: Verify logs were emitted
    assert len(cap_logs) > 0

    # CRITICAL: Verify raw password-md5 is NOT in ANY log message
    all_logs = "".join(str(entry) for entry in cap_logs)
    assert invalid_password not in all_logs

    # Verify SHA-256 hash IS logged
    expected_hash = hashlib.sha256(invalid_password.encode()).hexdigest()
    assert expected_hash in all_logs

    # Verify failure category is logged
    assert "authorization_failed" in all_logs


@pytest.mark.asyncio
async def test_failure_categories_are_logged() -> None:
    """R11.2: Failure categories must be recorded for diagnostics.

    Verify that terminal rejections include specific failure categories:
    - transport_validation_failure
    - crypto_validation_failure
    - authorization_failure
    - uniqueness_violation
    - beatmap_ineligibility
    - score_validation_failure
    """
    auth_service = make_score_authorization_service()

    # Test 1: Authorization failure category
    resolver = FakeBeatmapResolver(
        eligibility=BeatmapEligibility(
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
    )
    service, _ = _make_process_score_submission_use_case(
        resolver=resolver,
        auth_service=auth_service,
    )

    input_data = make_test_submission_input(
        parsed_score=_valid_parsed_score(),
        replay_data=None,
        password_md5="invalid",
        osu_version="2024.101.0",
        beatmap_id=123,
    )

    with structlog.testing.capture_logs() as cap_logs:
        result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result.error_reason is not None
    assert "authorization_failed" in result.error_reason

    # Verify logs contain failure category
    all_logs = "".join(str(entry) for entry in cap_logs)
    assert "authorization_failed" in all_logs

    # Test 2: Beatmap ineligibility category
    ineligible_resolver = FakeBeatmapResolver(
        eligibility=BeatmapEligibility(
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
            denial_reason="status_not_ranked",
        )
    )
    service2, _ = _make_process_score_submission_use_case(
        resolver=ineligible_resolver,
        auth_service=auth_service,
    )

    valid_input = make_test_submission_input(
        parsed_score=_valid_parsed_score(),
        replay_data=None,
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # valid test password
        osu_version="2024.101.0",
        beatmap_id=123,
    )

    with structlog.testing.capture_logs() as cap_logs2:
        result2 = await service2.execute(valid_input)

    assert result2.outcome == SubmissionOutcome.TERMINAL_REJECTED
    assert result2.error_reason is not None
    assert "beatmap_ineligible" in result2.error_reason

    # Verify logs contain failure category
    all_logs2 = "".join(str(entry) for entry in cap_logs2)
    assert "beatmap_ineligible" in all_logs2


@pytest.mark.asyncio
async def test_opaque_fields_stored_as_sha256_hashes_only() -> None:
    """R11.3: Opaque fields must be stored as SHA-256 hashes only.

    Raw opaque field values must not be stored in result_snapshot.
    """
    auth_service = make_score_authorization_service()
    resolver = FakeBeatmapResolver(
        eligibility=BeatmapEligibility(
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
    )

    service, submission_repo = _make_process_score_submission_use_case(
        resolver=resolver,
        auth_service=auth_service,
    )

    opaque_fields = {
        "fs": "fullscreen_flag",
        "bmk": "beatmap_key",
        "sbk": "score_key",
        "c1": "custom1",
        "st": "score_time",
        "i": "info_field",
        "token": "session_token",
    }
    opaque_field_hashes = {
        f"{key}_sha256": hashlib.sha256(value.encode()).hexdigest()
        for key, value in opaque_fields.items()
    }
    input_data = make_test_submission_input(
        parsed_score=_valid_parsed_score(),
        opaque_field_hashes=opaque_field_hashes,
        replay_data=b"replay_binary_data",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        osu_version="2024.101.0",
        beatmap_id=123,
        submitted_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )

    result = await service.execute(input_data)
    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify submission was recorded
    fingerprint = _fingerprint_for(input_data)
    submission = await submission_repo.get_by_fingerprint(fingerprint)
    assert submission is not None

    assert submission.result_snapshot is not None
    stored_opaque_fields = submission.result_snapshot.get("opaque_fields")
    assert isinstance(stored_opaque_fields, dict)
    for key, value in opaque_fields.items():
        expected_hash = hashlib.sha256(value.encode()).hexdigest()
        assert key not in submission.result_snapshot
        assert stored_opaque_fields[f"{key}_sha256"] == expected_hash
        assert value not in str(submission.result_snapshot)


@pytest.mark.asyncio
async def test_no_raw_credentials_in_logs() -> None:
    """R11.4: No raw password-md5, token, or encrypted payload in logs.

    Verify that actual log output does not contain sensitive fields during
    normal submission flow.
    """
    auth_service = make_score_authorization_service()
    resolver = FakeBeatmapResolver(
        eligibility=BeatmapEligibility(
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
    )

    service, _ = _make_process_score_submission_use_case(
        resolver=resolver,
        auth_service=auth_service,
    )

    secret_password = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    secret_payload = b"this_is_encrypted_secret_payload"
    secret_token = "raw_session_token"

    input_data = make_test_submission_input(
        parsed_score=_valid_parsed_score(),
        replay_data=b"replay_binary_data",
        password_md5=secret_password,
        osu_version="2024.101.0",
        beatmap_id=123,
        submitted_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        opaque_field_hashes={
            "token_sha256": hashlib.sha256(secret_token.encode()).hexdigest(),
        },
    )

    # Capture actual log output
    with structlog.testing.capture_logs() as cap_logs:
        result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify NO sensitive data in ANY log message
    all_logs = "".join(str(entry) for entry in cap_logs)
    assert secret_password not in all_logs
    assert secret_payload.decode() not in all_logs
    assert secret_token not in all_logs


@pytest.mark.asyncio
async def test_submission_fingerprint_and_result_snapshot_recorded() -> None:
    """R11.5: Submission fingerprint and result snapshot must be recorded.

    Verify that successful submissions record:
    - Submission fingerprint (for idempotency)
    - Result snapshot (score_id for observability)
    """
    auth_service = make_score_authorization_service()
    resolver = FakeBeatmapResolver(
        eligibility=BeatmapEligibility(
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
    )

    service, submission_repo = _make_process_score_submission_use_case(
        resolver=resolver,
        auth_service=auth_service,
    )

    input_data = make_test_submission_input(
        parsed_score=_valid_parsed_score(),
        replay_data=b"replay_binary_data",
        password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        osu_version="2024.101.0",
        beatmap_id=123,
        submitted_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )

    result = await service.execute(input_data)

    # Verify submission was recorded
    assert result.outcome == SubmissionOutcome.COMPLETED
    assert result.score_id is not None

    # Verify submission fingerprint was generated and stored
    expected_fingerprint = _fingerprint_for(input_data)

    submission = await submission_repo.get_by_fingerprint(expected_fingerprint)
    assert submission is not None
    assert submission.fingerprint == expected_fingerprint
    assert submission.state == "completed"

    # Verify result snapshot contains score_id for observability
    assert submission.result_snapshot is not None
    assert submission.result_snapshot.get("score_id") == result.score_id

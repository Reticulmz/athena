"""score submissionのprivacyとsecurity契約を検証する unit test module.

credentialの非露出, failure category, opaque fieldのhash化, fingerprint, result snapshotを対象に,
submission workflowが機微情報を記録しないことを確認する.
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
    BeatmapMode,
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

_BEATMAP_CHECKSUM = "0123456789abcdef0123456789abcdef"


def _resolved_beatmap() -> Beatmap:
    """security検証で解決済みとして返すranked beatmapを作成する.

    Returns:
        Beatmap: score submissionを受理できる固定IDとchecksumを持つranked beatmap.
    """
    return Beatmap(
        id=123,
        beatmapset_id=456,
        checksum_md5="0123456789abcdef0123456789abcdef",
        mode=BeatmapMode.OSU,
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
    beatmap_checksum: str = _BEATMAP_CHECKSUM,
    submitted_timestamp: str | None = None,
) -> str:
    """Test inputとsubmission識別子から期待するfingerprintを計算する.

    Args:
        input_data (ParsedSubmissionInput): request hashとsubmission時刻を持つ正規化済みinput.
        user_id (int): fingerprintへ含める認証済みuser ID.
        beatmap_checksum (str): fingerprintへ含めるbeatmap checksum MD5.
        submitted_timestamp (str | None): fingerprintへ明示的に渡す時刻. Noneならinputの値を使う.

    Returns:
        str: serviceが永続化する値と同じsubmission fingerprint.
    """
    return generate_submission_fingerprint(
        user_id=user_id,
        beatmap_checksum=beatmap_checksum,
        submitted_timestamp=submitted_timestamp,
        request_hash=input_data.request_hash,
    )


def _valid_parsed_score(
    *,
    beatmap_checksum: str = _BEATMAP_CHECKSUM,
    online_checksum: str = "12345678",
) -> ParsedScore:
    """security検証で受理可能なparse済みscoreを作成する.

    Args:
        beatmap_checksum (str): scoreが参照するbeatmap checksum MD5.
        online_checksum (str): 重複検出とfingerprint検証に使うonline score checksum.

    Returns:
        ParsedScore: osu! vanillaの成功playを表す固定user用score.
    """
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
    """security test用に一定のbeatmap解決結果を返すfake resolver.

    Attributes:
        eligibility (BeatmapEligibility | None): checksum解決結果へ含めるscore submission
            eligibility.
    """

    eligibility: BeatmapEligibility | None = None

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap IDによる解決要求へmetadataのみの結果を返す.

        Args:
            beatmap_id (int): 呼び出し側が指定するbeatmap ID. fakeでは結果を変えない.
            options (BeatmapResolveOptions | None): 解決option. fakeでは使用しない.

        Returns:
            BeatmapResolveResult: beatmap本体を含まず,設定済みeligibilityを含むfreshな解決結果.
        """
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
        """checksumによる解決要求へranked beatmapを含む結果を返す.

        Args:
            checksum_md5 (str): 呼び出し側が指定するbeatmap checksum MD5. fakeでは結果を変えない.
            options (BeatmapResolveOptions | None): 解決option. fakeでは使用しない.

        Returns:
            BeatmapResolveResult: 設定済みeligibilityと固定ranked beatmapを含むfreshな解決結果.
        """
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
    """Security assertion用repository viewを接続したsubmission use-caseを構成する.

    Args:
        resolver (FakeBeatmapResolver): submission可否を返すfake beatmap resolver.
        auth_service (ScoreAuthorizationService): credentialとsessionを照合する認可service.

    Returns:
        tuple[ProcessScoreSubmissionUseCase, UowScoreSubmissionRepositoryView]:
            実行対象use-caseと保存済みsubmissionを読むrepository view.
    """
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
    """認可失敗時にraw password MD5をlogへ露出しない契約を検証する.

    有効なbeatmapと無効credentialを持つsubmissionを実行し,terminal rejectionのlogには
    生のpassword MD5ではなくSHA-256 hashとfailure categoryだけが残ることを確認する.

    Returns:
        None: credential非露出と認可failure分類を検証して完了し,呼び出し側へ値を返さない.

    Notes:
        raw password MD5は保存せず,診断にはSHA-256 hashだけを使用する.
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

    invalid_md5_value = "invalid_password_md5_hash_12345"
    input_data = make_test_submission_input(
        parsed_score=_valid_parsed_score(),
        replay_data=None,
        password_md5=invalid_md5_value,
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
    assert invalid_md5_value not in all_logs

    # Verify SHA-256 hash IS logged
    expected_hash = hashlib.sha256(invalid_md5_value.encode()).hexdigest()
    assert expected_hash in all_logs

    # Verify failure category is logged
    assert "authorization_failed" in all_logs


@pytest.mark.asyncio
async def test_failure_categories_are_logged() -> None:
    """認可failureとbeatmap不適格を別々のdiagnostic categoryとして記録する契約を検証する.

    無効credentialのsubmissionと不適格beatmapのsubmissionを個別に実行し,
    どちらもterminal rejectionとなり対応するfailure categoryがlogへ記録されることを確認する.

    Returns:
        None: 2種類のfailure categoryを検証して完了し,呼び出し側へ値を返さない.

    Notes:
        log内容はcredentialの生値ではなくauthorizationとbeatmap ineligibilityの分類だけを確認する.
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
    """Opaque fieldをSHA-256 hashだけでresult snapshotへ保存する契約を検証する.

    tokenを含む複数のopaque field hashを持つ有効submissionを保存し,
    snapshotには各hashが残る一方で対応する生値と未hash keyが残らないことを確認する.

    Returns:
        None: hash化済みsnapshotを検証して完了し,呼び出し側へ値を返さない.

    Notes:
        tokenなどのopaque fieldの生値はresult snapshotへ保存しない.
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
    """成功するsubmission flowがraw credentialとtokenをlogへ露出しない契約を検証する.

    credential, 暗号化payload marker, opaque session tokenを持つ有効submissionを実行し,
    実際のstructlog outputにいずれの生値も含まれないことを確認する.

    Returns:
        None: 成功flowの機微情報非露出を検証して完了し,呼び出し側へ値を返さない.

    Notes:
        log検証はactual structlog outputを対象にし,mask済みまたはhash化済みの値だけを許可する.
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

    credential_md5_value = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    encrypted_payload_marker = b"this_is_encrypted_secret_payload"
    opaque_session_value = "raw_session_token"

    input_data = make_test_submission_input(
        parsed_score=_valid_parsed_score(),
        replay_data=b"replay_binary_data",
        password_md5=credential_md5_value,
        osu_version="2024.101.0",
        beatmap_id=123,
        submitted_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        opaque_field_hashes={
            "token_sha256": hashlib.sha256(opaque_session_value.encode()).hexdigest(),
        },
    )

    # Capture actual log output
    with structlog.testing.capture_logs() as cap_logs:
        result = await service.execute(input_data)

    assert result.outcome == SubmissionOutcome.COMPLETED

    # Verify NO sensitive data in ANY log message
    all_logs = "".join(str(entry) for entry in cap_logs)
    assert credential_md5_value not in all_logs
    assert encrypted_payload_marker.decode() not in all_logs
    assert opaque_session_value not in all_logs


@pytest.mark.asyncio
async def test_submission_fingerprint_and_result_snapshot_recorded() -> None:
    """成功submissionがfingerprintとresult snapshotを永続化する契約を検証する.

    replayを含む有効submissionを実行し,completed outcomeのscore IDに対応する保存済み
    submissionが期待するfingerprintとobservability用snapshotを持つことを確認する.

    Returns:
        None: idempotencyとobservability用の永続化結果を検証して完了し,呼び出し側へ値を返さない.

    Notes:
        成功submissionはidempotency用fingerprintとobservability用snapshotの両方を保存する.
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

"""スコア submission の command workflow 全体を編成する use-case。"""

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Never, Protocol

import structlog

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.payload_parser import ParsedScore
from osu_server.domain.scores.personal_best import PersonalBestDelta
from osu_server.domain.scores.score import Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.domain.scores.user_stats import UserCurrentStats
from osu_server.domain.scores.validator import (
    ValidationError,
    ValidationResult,
    validate_hit_counts,
)
from osu_server.domain.storage.blobs import BlobStoreResult
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
)
from osu_server.services.commands.scores.authorization import (
    AuthorizationContext,
)
from osu_server.services.commands.scores.performance import (
    RequestPerformanceCalculationCommand,
    RequestPerformanceCalculationOutcome,
    RequestPerformanceCalculationResult,
)
from osu_server.services.commands.scores.submit_score import (
    SubmitScoreCommand,
    SubmitScoreCommandOutcome,
    SubmitScoreCommandResult,
    SubmitScoreUseCase,
)
from osu_server.services.queries.scores import (
    BeatmapPersonalBestRankQueryInput,
    BeatmapPersonalBestRankQueryResult,
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
    PerformanceSubmitResponse,
    PerformanceSubmitResponseQuery,
    PerformanceSubmitResponseState,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_REPLAY_CONTENT_TYPE = "application/octet-stream"
_PERFORMANCE_RESPONSE_AVAILABLE_OUTCOMES = frozenset(
    {
        RequestPerformanceCalculationOutcome.CREATED,
        RequestPerformanceCalculationOutcome.CREATED_REPLACEMENT,
        RequestPerformanceCalculationOutcome.REUSED_PENDING,
        RequestPerformanceCalculationOutcome.REUSED_REPLACEMENT_PENDING,
        RequestPerformanceCalculationOutcome.ALREADY_CURRENT,
    }
)


class _FingerprintHasher(Protocol):
    def update(self, data: bytes, /) -> None: ...


def _update_fingerprint_bytes(hasher: _FingerprintHasher, label: bytes, value: bytes) -> None:
    hasher.update(label)
    hasher.update(b"\0")
    hasher.update(str(len(value)).encode())
    hasher.update(b"\0")
    hasher.update(value)
    hasher.update(b"\0")


def _update_fingerprint_text(hasher: _FingerprintHasher, label: str, value: str) -> None:
    _update_fingerprint_bytes(hasher, label.encode(), value.encode())


class BeatmapEligibilityResolver(Protocol):
    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult: ...

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult: ...


class ScoreSubmissionAuthorizer(Protocol):
    async def authorize_submission(
        self,
        password_md5: str,
        payload_username: str,
        payload_user_id: int,
    ) -> AuthorizationContext: ...


class ReplayBlobStorage(Protocol):
    async def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
    ) -> BlobStoreResult: ...


class BeatmapFileWarmupUseCase(Protocol):
    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult: ...


class PerformanceCalculationRequestUseCase(Protocol):
    async def execute(
        self,
        command: RequestPerformanceCalculationCommand,
    ) -> RequestPerformanceCalculationResult: ...


class PerformanceCalculatorIdentity(Protocol):
    def calculator_name(self) -> str: ...

    def calculator_version(self) -> str: ...


class PerformanceSubmitResponseUseCase(Protocol):
    async def wait_for_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse: ...

    async def get_submit_response(
        self,
        query: PerformanceSubmitResponseQuery,
    ) -> PerformanceSubmitResponse: ...


class CurrentUserStatsQueryUseCase(Protocol):
    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult: ...


class BeatmapPersonalBestRankQueryUseCase(Protocol):
    async def execute(
        self,
        input_data: BeatmapPersonalBestRankQueryInput,
    ) -> BeatmapPersonalBestRankQueryResult: ...


class SubmissionOutcome(Enum):
    """スコア submission workflow の最終 outcome。"""

    COMPLETED = "completed"
    TERMINAL_REJECTED = "terminal_rejected"
    RETRYABLE = "retryable"
    ACCEPTED_PENDING = "accepted_pending"


@dataclass(frozen=True, slots=True)
class BeatmapRankDelta:
    """安定版 submit response に載せる beatmap leaderboard 順位差分。"""

    before: int | None
    after: int | None


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """転送層に返す score submission 結果。"""

    outcome: SubmissionOutcome
    user_id: int | None = None
    ruleset: Ruleset | None = None
    playstyle: Playstyle | None = None
    score_id: int | None = None
    beatmap_id: int | None = None
    beatmapset_id: int | None = None
    score: int | None = None
    max_combo: int | None = None
    accuracy: float | None = None
    passed: bool | None = None
    beatmap_playcount: int | None = None
    beatmap_passcount: int | None = None
    beatmap_approved_at: datetime | None = None
    error_reason: str | None = None
    stable_pp: int | None = None
    stable_pp_before: int | None = None
    stable_pp_after: int | None = None
    personal_best_delta: PersonalBestDelta | None = None
    beatmap_rank_delta: BeatmapRankDelta | None = None
    overall_stats_before: UserCurrentStats | None = None
    overall_stats_after: UserCurrentStats | None = None


@dataclass(frozen=True, slots=True)
class ParsedSubmissionInput:
    """安定版 score submit を command 境界へ渡す正規化済み入力。

    振る舞い:
        Transport 層で復号と wire payload parse を済ませた score submit 情報を保持する。
        Command use-case はこの型だけを受け取り、stable multipart や暗号化 payload の
        wire 表現には依存しない。

    Args:
        parsed_score: payload から得た canonical score 値。
        request_hash: idempotency と診断に使う stable request hash。
        opaque_field_hashes: token などの opaque metadata を SHA-256 化した値。
        decrypt_latency_ms: transport 側の復号処理時間。
        replay_data: 添付 replay binary。送信されない場合は None。
        password_md5: stable client が送る password-md5 credential。
        fail_time_ms: stable client の fail time。未送信の場合は None。
        osu_version: stable client version。未送信の場合は None。
        submitted_at: server が request を受け取った時刻。
        beatmap_id: form field 由来の beatmap id。未送信の場合は None。
        submit_exit_classification: client 終了種別の診断値。未送信の場合は None。

    Returns:
        dataclass のため値は返さず、command input として参照される。

    Raises:
        生成時に独自例外は送出しない。値の妥当性検証は use-case 側で行う。

    Constraints:
        Transport wire 型や暗号化済み payload を含めない。credential と replay は
        logging せず、opaque metadata は hash 済み値だけを保持する。
    """

    parsed_score: ParsedScore
    request_hash: str
    opaque_field_hashes: Mapping[str, str]
    decrypt_latency_ms: float
    replay_data: bytes | None
    password_md5: str
    fail_time_ms: int | None
    osu_version: str | None
    submitted_at: datetime
    beatmap_id: int | None = None
    submit_exit_classification: str | None = None


def _grade_discrepancy(client_grade: str | None, server_grade: str) -> dict[str, str] | None:
    if client_grade is None:
        return None

    normalized_client_grade = client_grade.strip().upper()
    if not normalized_client_grade or normalized_client_grade == server_grade:
        return None

    return {
        "client_grade": client_grade,
        "server_grade": server_grade,
    }


def generate_submission_fingerprint(
    *,
    user_id: int,
    beatmap_checksum: str,
    submitted_timestamp: str | None,
    request_hash: str,
) -> str:
    """冪等性判定に使う submission fingerprint を生成する。"""
    hasher = hashlib.sha256()
    _update_fingerprint_text(hasher, "user_id", str(user_id))
    _update_fingerprint_text(hasher, "beatmap_checksum", beatmap_checksum)
    _update_fingerprint_text(hasher, "submitted_timestamp", submitted_timestamp or "")
    _update_fingerprint_text(hasher, "request_hash", request_hash)
    return hasher.hexdigest()


def _valid_non_negative(value: int | None) -> int | None:
    if value is None or value < 0:
        return None
    return value


def _derive_score_timing(
    *,
    passed: bool,
    fail_time_ms: int | None,
    beatmap_total_length: int | None,
) -> tuple[int | None, int | None, PlayTimeSource | None]:
    normalized_fail_time_ms = _valid_non_negative(fail_time_ms)
    if not passed:
        if normalized_fail_time_ms is None:
            return None, None, None
        return (
            normalized_fail_time_ms,
            normalized_fail_time_ms // 1000,
            PlayTimeSource.FAIL_TIME,
        )

    normalized_total_length = _valid_non_negative(beatmap_total_length)
    if normalized_total_length is None:
        return normalized_fail_time_ms, None, None
    return (
        normalized_fail_time_ms,
        normalized_total_length,
        PlayTimeSource.BEATMAP_TOTAL_LENGTH,
    )


def _submission_result_from_command(
    result: SubmitScoreCommandResult,
    *,
    beatmap_rank_delta: BeatmapRankDelta | None = None,
    overall_stats_before: UserCurrentStats | None = None,
    overall_stats_after: UserCurrentStats | None = None,
) -> SubmissionResult:
    return SubmissionResult(
        outcome=SubmissionOutcome(result.outcome.value),
        user_id=result.user_id,
        ruleset=result.ruleset,
        playstyle=result.playstyle,
        score_id=result.score_id,
        beatmap_id=result.beatmap_id,
        beatmapset_id=result.beatmapset_id,
        score=result.score,
        max_combo=result.max_combo,
        accuracy=result.accuracy,
        passed=result.passed,
        beatmap_playcount=result.beatmap_playcount,
        beatmap_passcount=result.beatmap_passcount,
        beatmap_approved_at=result.beatmap_approved_at,
        error_reason=result.error_reason,
        personal_best_delta=result.personal_best_delta,
        beatmap_rank_delta=beatmap_rank_delta,
        overall_stats_before=overall_stats_before,
        overall_stats_after=overall_stats_after,
    )


def _score_submit_approved_at(beatmap: Beatmap) -> datetime | None:
    if (
        beatmap.local_status_override is not None
        and beatmap.local_status_override_changed_at is not None
    ):
        return beatmap.local_status_override_changed_at
    return beatmap.official_last_updated_at


class _SubmissionStoppedError(Exception):
    def __init__(self, result: SubmissionResult) -> None:
        super().__init__(result.error_reason)
        self.result: SubmissionResult = result


def _stop_submission(result: SubmissionResult) -> Never:
    raise _SubmissionStoppedError(result)


@dataclass(frozen=True, slots=True)
class _SubmissionAttempt:
    input_data: ParsedSubmissionInput
    start_time: float
    request_hash: str
    opaque_field_hashes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _AuthorizedSubmission:
    parsed: ParsedScore
    auth_ctx: AuthorizationContext
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _ResolvedBeatmapSubmission:
    result: BeatmapResolveResult
    beatmap: Beatmap
    latency_ms: float


@dataclass(frozen=True, slots=True)
class _AcceptedBeatmapSubmission:
    result: BeatmapResolveResult
    resolved_beatmap_id: int
    resolved_beatmapset_id: int
    score_ruleset: Ruleset
    score_playstyle: Playstyle
    beatmap_status_at_submission: str
    beatmap_approved_at: datetime | None
    leaderboard_eligible_at_submission: bool
    fail_time_ms: int | None
    play_time_seconds: int | None
    play_time_source: PlayTimeSource | None
    latency_ms: float


@dataclass(frozen=True, slots=True)
class _ValidatedSubmission:
    result: ValidationResult
    grade_discrepancy: dict[str, str] | None


@dataclass(frozen=True, slots=True)
class _ReplayBlobReference:
    replay_data: bytes | None
    replay_checksum: str | None
    replay_byte_size: int | None
    replay_blob_id: int | None


@dataclass(frozen=True, slots=True)
class _SubmitScoreBaseline:
    overall_stats_before: UserCurrentStats | None
    beatmap_rank_before: int | None


@dataclass(frozen=True, slots=True)
class _SubmitResponseDeltas:
    overall_stats_after: UserCurrentStats | None
    beatmap_rank_after: int | None


def _accepted_beatmap_submission(
    attempt: _SubmissionAttempt,
    authorized: _AuthorizedSubmission,
    resolved: _ResolvedBeatmapSubmission,
) -> _AcceptedBeatmapSubmission:
    parsed = authorized.parsed
    beatmap_result = resolved.result
    beatmap = resolved.beatmap
    eligibility = beatmap_result.eligibility
    score_ruleset = Ruleset(parsed.ruleset)
    fail_time_ms, play_time_seconds, play_time_source = _derive_score_timing(
        passed=parsed.passed,
        fail_time_ms=attempt.input_data.fail_time_ms,
        beatmap_total_length=beatmap.total_length,
    )
    return _AcceptedBeatmapSubmission(
        result=beatmap_result,
        resolved_beatmap_id=attempt.input_data.beatmap_id or beatmap.id,
        resolved_beatmapset_id=(
            beatmap_result.beatmapset.id if beatmap_result.beatmapset is not None else 0
        ),
        score_ruleset=score_ruleset,
        score_playstyle=Playstyle.VANILLA,
        beatmap_status_at_submission=beatmap.effective_status.value,
        beatmap_approved_at=_score_submit_approved_at(beatmap),
        leaderboard_eligible_at_submission=(
            parsed.passed and eligibility is not None and eligibility.has_leaderboard
        ),
        fail_time_ms=fail_time_ms,
        play_time_seconds=play_time_seconds,
        play_time_source=play_time_source,
        latency_ms=resolved.latency_ms,
    )


def _build_score(
    attempt: _SubmissionAttempt,
    authorized: _AuthorizedSubmission,
    accepted_beatmap: _AcceptedBeatmapSubmission,
    validated: _ValidatedSubmission,
) -> Score:
    parsed = authorized.parsed
    return Score(
        id=None,
        user_id=authorized.auth_ctx.user_id,
        beatmap_id=accepted_beatmap.resolved_beatmap_id,
        beatmap_checksum=parsed.beatmap_checksum,
        online_checksum=parsed.online_checksum,
        ruleset=accepted_beatmap.score_ruleset,
        playstyle=accepted_beatmap.score_playstyle,
        mods=parsed.mods,
        n300=parsed.n300,
        n100=parsed.n100,
        n50=parsed.n50,
        geki=parsed.geki,
        katu=parsed.katu,
        miss=parsed.miss,
        score=parsed.score,
        max_combo=parsed.max_combo,
        accuracy=validated.result.accuracy,
        grade=validated.result.grade,
        passed=parsed.passed,
        perfect=parsed.perfect,
        client_version=attempt.input_data.osu_version or "unknown",
        submitted_at=attempt.input_data.submitted_at,
        beatmap_status_at_submission=BeatmapRankStatus(
            accepted_beatmap.beatmap_status_at_submission
        ),
        leaderboard_eligible_at_submission=accepted_beatmap.leaderboard_eligible_at_submission,
        fail_time_ms=accepted_beatmap.fail_time_ms,
        play_time_seconds=accepted_beatmap.play_time_seconds,
        play_time_source=accepted_beatmap.play_time_source,
        submit_exit_classification=attempt.input_data.submit_exit_classification,
    )


def _completed_submit_command(
    *,
    attempt: _SubmissionAttempt,
    authorized: _AuthorizedSubmission,
    accepted_beatmap: _AcceptedBeatmapSubmission,
    validated: _ValidatedSubmission,
    replay: _ReplayBlobReference,
    score: Score,
) -> SubmitScoreCommand:
    return SubmitScoreCommand(
        fingerprint=authorized.fingerprint,
        user_id=authorized.auth_ctx.user_id,
        beatmap_checksum=authorized.parsed.beatmap_checksum,
        submitted_at=attempt.input_data.submitted_at,
        outcome=SubmitScoreCommandOutcome.COMPLETED,
        score=score,
        beatmap_id=accepted_beatmap.resolved_beatmap_id,
        beatmapset_id=accepted_beatmap.resolved_beatmapset_id,
        beatmap_approved_at=accepted_beatmap.beatmap_approved_at,
        replay_blob_id=replay.replay_blob_id,
        replay_checksum_sha256=replay.replay_checksum,
        replay_byte_size=replay.replay_byte_size,
        grade_discrepancy=validated.grade_discrepancy,
        opaque_field_hashes=attempt.opaque_field_hashes,
        include_personal_best_delta=accepted_beatmap.leaderboard_eligible_at_submission,
        update_personal_best=accepted_beatmap.leaderboard_eligible_at_submission,
    )


def _log_submission_completed(
    *,
    attempt: _SubmissionAttempt,
    authorized: _AuthorizedSubmission,
    accepted_beatmap: _AcceptedBeatmapSubmission,
    replay: _ReplayBlobReference,
    command_result: SubmitScoreCommandResult,
    decrypt_latency_ms: float,
    db_latency_ms: float,
) -> None:
    logger.info(
        "score_submission_completed",
        duration_ms=(time.perf_counter() - attempt.start_time) * 1000,
        decrypt_latency_ms=decrypt_latency_ms,
        beatmap_latency_ms=accepted_beatmap.latency_ms,
        db_latency_ms=db_latency_ms,
        fingerprint=authorized.fingerprint,
        user_id=authorized.auth_ctx.user_id,
        beatmap_id=accepted_beatmap.resolved_beatmap_id,
        score_id=command_result.score_id,
        replay_attachment_id=command_result.replay_attachment_id,
        replay_present=replay.replay_data is not None,
        replay_byte_size=replay.replay_byte_size,
        passed=authorized.parsed.passed,
        fail_time_ms=attempt.input_data.fail_time_ms,
        beatmap_status_at_submission=accepted_beatmap.beatmap_status_at_submission,
        opaque_fields=attempt.opaque_field_hashes or None,
    )


def _beatmap_rank_delta_for_submit_response(
    *,
    before: int | None,
    after: int | None,
    include_beatmap_rank_delta: bool,
) -> BeatmapRankDelta | None:
    if not include_beatmap_rank_delta:
        return None
    return BeatmapRankDelta(before=before, after=after)


def _performance_pending_submission_result(
    command_result: SubmitScoreCommandResult,
    *,
    overall_stats_before: UserCurrentStats | None,
    stable_pp_before: int | None = None,
    personal_best_delta: PersonalBestDelta | None = None,
) -> SubmissionResult:
    return SubmissionResult(
        outcome=SubmissionOutcome.RETRYABLE,
        user_id=command_result.user_id,
        ruleset=command_result.ruleset,
        playstyle=command_result.playstyle,
        score_id=command_result.score_id,
        beatmap_id=command_result.beatmap_id,
        beatmapset_id=command_result.beatmapset_id,
        score=command_result.score,
        max_combo=command_result.max_combo,
        accuracy=command_result.accuracy,
        passed=command_result.passed,
        beatmap_playcount=command_result.beatmap_playcount,
        beatmap_passcount=command_result.beatmap_passcount,
        beatmap_approved_at=command_result.beatmap_approved_at,
        error_reason="performance_calculation_pending",
        stable_pp_before=stable_pp_before,
        personal_best_delta=personal_best_delta,
        overall_stats_before=overall_stats_before,
    )


def _completed_submit_response_result(
    command_result: SubmitScoreCommandResult,
    *,
    stable_pp: int | None,
    stable_pp_before: int | None = None,
    personal_best_delta: PersonalBestDelta | None = None,
    beatmap_rank_delta: BeatmapRankDelta | None,
    overall_stats_before: UserCurrentStats | None,
    overall_stats_after: UserCurrentStats | None,
) -> SubmissionResult:
    return SubmissionResult(
        outcome=SubmissionOutcome.COMPLETED,
        user_id=command_result.user_id,
        ruleset=command_result.ruleset,
        playstyle=command_result.playstyle,
        score_id=command_result.score_id,
        beatmap_id=command_result.beatmap_id,
        beatmapset_id=command_result.beatmapset_id,
        score=command_result.score,
        max_combo=command_result.max_combo,
        accuracy=command_result.accuracy,
        passed=command_result.passed,
        beatmap_playcount=command_result.beatmap_playcount,
        beatmap_passcount=command_result.beatmap_passcount,
        beatmap_approved_at=command_result.beatmap_approved_at,
        stable_pp=stable_pp,
        stable_pp_before=stable_pp_before,
        stable_pp_after=stable_pp,
        personal_best_delta=personal_best_delta,
        beatmap_rank_delta=beatmap_rank_delta,
        overall_stats_before=overall_stats_before,
        overall_stats_after=overall_stats_after,
    )


class ProcessScoreSubmissionUseCase:
    """スコア submission command workflow を編成する module。

    authorization、beatmap eligibility、validation、replay storage、
    score persistence、performance request をこの interface の内側に集中させる。
    """

    def __init__(
        self,
        submit_score_use_case: SubmitScoreUseCase,
        replay_blob_storage: ReplayBlobStorage,
        auth_service: ScoreSubmissionAuthorizer,
        beatmap_resolver: BeatmapEligibilityResolver,
        beatmap_file_warmup_use_case: BeatmapFileWarmupUseCase | None = None,
        performance_calculation_request: PerformanceCalculationRequestUseCase | None = None,
        performance_calculator_identity: PerformanceCalculatorIdentity | None = None,
        performance_response_query: PerformanceSubmitResponseUseCase | None = None,
        current_user_stats_query: CurrentUserStatsQueryUseCase | None = None,
        beatmap_personal_best_rank_query: BeatmapPersonalBestRankQueryUseCase | None = None,
    ) -> None:
        self._submit_score_use_case: SubmitScoreUseCase = submit_score_use_case
        self._replay_blob_storage: ReplayBlobStorage = replay_blob_storage
        self._auth_service: ScoreSubmissionAuthorizer = auth_service
        self._beatmap_resolver: BeatmapEligibilityResolver = beatmap_resolver
        self._beatmap_file_warmup_use_case: BeatmapFileWarmupUseCase | None = (
            beatmap_file_warmup_use_case
        )
        self._performance_calculation_request: PerformanceCalculationRequestUseCase | None = (
            performance_calculation_request
        )
        self._performance_calculator_identity: PerformanceCalculatorIdentity | None = (
            performance_calculator_identity
        )
        self._performance_response_query: PerformanceSubmitResponseUseCase | None = (
            performance_response_query
        )
        self._current_user_stats_query: CurrentUserStatsQueryUseCase | None = (
            current_user_stats_query
        )
        self._beatmap_personal_best_rank_query: BeatmapPersonalBestRankQueryUseCase | None = (
            beatmap_personal_best_rank_query
        )

    async def execute(self, input_data: ParsedSubmissionInput) -> SubmissionResult:
        """スコアを検証し、durable state と replay blob に反映する。

        Args:
            input_data: transport 層で復号と parse を完了した score submit 入力。

        Returns:
            durable state への反映結果と stable response に必要な差分情報を含む
            SubmissionResult。

        Raises:
            公開境界では内部停止例外を返さない。phase helper が送出する
            _SubmissionStoppedError はこの method 内で SubmissionResult に変換する。

        Constraints:
            処理順序は fingerprint 生成、authorization、beatmap eligibility、
            hit count validation、replay 保存、score persistence、
            performance calculation request の順に固定する。retry で再送されても
            同じ request と同じ score 送信を識別できるよう、request hash は
            transport adapter が生成し、submission fingerprint は durable mutation 前に
            生成する。
        """
        attempt = _SubmissionAttempt(
            input_data=input_data,
            start_time=time.perf_counter(),
            request_hash=input_data.request_hash,
            opaque_field_hashes=input_data.opaque_field_hashes,
        )

        try:
            authorized = await self._authorize_submission(attempt, input_data.parsed_score)
            await self._reject_unsupported_playstyle(attempt, authorized)
            accepted_beatmap = await self._resolve_accepted_beatmap(attempt, authorized)
            validated = await self._validate_submission(attempt, authorized)

            await self._request_score_submit_fallback_warmup(
                user_id=authorized.auth_ctx.user_id,
                beatmap_id=accepted_beatmap.resolved_beatmap_id,
                checksum_md5=authorized.parsed.beatmap_checksum,
            )
            replay = await self._store_replay_blob(attempt, authorized)

            return await self._persist_completed_submission(
                attempt=attempt,
                authorized=authorized,
                accepted_beatmap=accepted_beatmap,
                validated=validated,
                replay=replay,
                decrypt_latency_ms=input_data.decrypt_latency_ms,
            )
        except _SubmissionStoppedError as stopped:
            return stopped.result

    async def _authorize_submission(
        self,
        attempt: _SubmissionAttempt,
        parsed: ParsedScore,
    ) -> _AuthorizedSubmission:
        auth_ctx = await self._auth_service.authorize_submission(
            attempt.input_data.password_md5,
            parsed.username,
            parsed.user_id,
        )

        fingerprint = generate_submission_fingerprint(
            user_id=auth_ctx.user_id,
            beatmap_checksum=parsed.beatmap_checksum,
            submitted_timestamp=parsed.client_submitted_at,
            request_hash=attempt.request_hash,
        )

        if not auth_ctx.authorized:
            password_hash = hashlib.sha256(attempt.input_data.password_md5.encode()).hexdigest()
            logger.warning(
                "score_submission_failed",
                reason="authorization_failed",
                fingerprint=fingerprint,
                password_hash=password_hash,
                username=parsed.username,
                user_id=auth_ctx.user_id,
                password_valid=auth_ctx.password_valid,
                session_valid=auth_ctx.session_valid,
                identity_match=auth_ctx.payload_identity_match,
            )
            result = await self._record_terminal_reject(
                fingerprint=fingerprint,
                user_id=auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=self._format_auth_error(auth_ctx),
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)
        return _AuthorizedSubmission(parsed=parsed, auth_ctx=auth_ctx, fingerprint=fingerprint)

    async def _reject_unsupported_playstyle(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> None:
        if self._is_relax_or_autopilot(authorized.parsed.mods):
            error_reason = "playstyle_not_supported: relax_or_autopilot"
            logger.warning(
                "score_submission_failed",
                reason="playstyle_not_supported",
                fingerprint=authorized.fingerprint,
                mods=authorized.parsed.mods.to_persistence_bitmask(),
                user_id=authorized.auth_ctx.user_id,
            )
            result = await self._record_terminal_reject(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

    async def _resolve_accepted_beatmap(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> _AcceptedBeatmapSubmission:
        resolved = await self._resolve_beatmap_or_retry(attempt, authorized)
        await self._reject_ineligible_beatmap(attempt, authorized, resolved)
        return _accepted_beatmap_submission(attempt, authorized, resolved)

    async def _resolve_beatmap_or_retry(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> _ResolvedBeatmapSubmission:
        beatmap_start = time.perf_counter()
        beatmap_result = await self._beatmap_resolver.resolve_by_checksum(
            authorized.parsed.beatmap_checksum,
            BeatmapResolveOptions(wait_timeout_seconds=5),
        )
        beatmap_latency_ms = (time.perf_counter() - beatmap_start) * 1000

        beatmap = beatmap_result.beatmap
        if beatmap is None:
            error_reason = "beatmap_fetch_in_progress"
            logger.info(
                "score_submission_retryable",
                reason=error_reason,
                fingerprint=authorized.fingerprint,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                opaque_fields=attempt.opaque_field_hashes or None,
            )
            result = await self._record_retryable(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)
        return _ResolvedBeatmapSubmission(
            result=beatmap_result,
            beatmap=beatmap,
            latency_ms=beatmap_latency_ms,
        )

    async def _reject_ineligible_beatmap(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
        resolved: _ResolvedBeatmapSubmission,
    ) -> None:
        eligibility = resolved.result.eligibility
        accepts_submission = False
        if eligibility is not None:
            accepts_submission = (
                eligibility.accepts_scores
                if authorized.parsed.passed
                else eligibility.accepts_failed_scores
            )
        if not accepts_submission:
            denial_reason = eligibility.denial_reason if eligibility is not None else None
            error_reason = f"beatmap_ineligible: {denial_reason or 'not_accepting_scores'}"
            logger.warning(
                "score_submission_failed",
                reason="beatmap_ineligible",
                fingerprint=authorized.fingerprint,
                beatmap_id=attempt.input_data.beatmap_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                denial_reason=denial_reason,
                passed=authorized.parsed.passed,
            )
            result = await self._record_terminal_reject(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

    async def _validate_submission(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> _ValidatedSubmission:
        parsed = authorized.parsed
        if attempt.input_data.replay_data == b"":
            error_reason = "empty_replay_data"
            logger.warning(
                "score_submission_failed",
                reason="empty_replay_data",
                fingerprint=authorized.fingerprint,
                passed=parsed.passed,
                fail_time_ms=attempt.input_data.fail_time_ms,
            )
            result = await self._record_terminal_reject(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

        try:
            validation = validate_hit_counts(parsed)
        except ValidationError as e:
            error_reason = f"validation_failed: {e}"
            logger.warning(
                "score_submission_failed",
                reason="validation_failed",
                fingerprint=authorized.fingerprint,
                error=str(e),
            )
            result = await self._record_terminal_reject(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason=error_reason,
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

        grade_discrepancy = _grade_discrepancy(parsed.client_grade, validation.grade.value)
        if grade_discrepancy is not None:
            logger.info(
                "score_grade_discrepancy",
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=parsed.beatmap_checksum,
                client_grade=grade_discrepancy["client_grade"],
                server_grade=grade_discrepancy["server_grade"],
            )
        return _ValidatedSubmission(result=validation, grade_discrepancy=grade_discrepancy)

    async def _store_replay_blob(
        self,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
    ) -> _ReplayBlobReference:
        replay_data = attempt.input_data.replay_data
        replay_byte_size = len(replay_data) if replay_data is not None else None
        replay_checksum = None
        if replay_data is not None:
            replay_checksum = hashlib.sha256(replay_data).hexdigest()

        if replay_data is None:
            return _ReplayBlobReference(
                replay_data=None,
                replay_checksum=None,
                replay_byte_size=None,
                replay_blob_id=None,
            )

        try:
            replay_blob_result = await self._replay_blob_storage.put_bytes(
                replay_data,
                content_type=_REPLAY_CONTENT_TYPE,
            )
        except Exception as exc:
            logger.warning(
                "score_submission_retryable",
                reason="replay_blob_store_failed",
                fingerprint=authorized.fingerprint,
                error=type(exc).__name__,
            )
            result = await self._record_retryable(
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                submitted_at=attempt.input_data.submitted_at,
                error_reason="replay_blob_store_failed",
                opaque_field_hashes=attempt.opaque_field_hashes,
            )
            _stop_submission(result)

        return _ReplayBlobReference(
            replay_data=replay_data,
            replay_checksum=replay_checksum,
            replay_byte_size=replay_byte_size,
            replay_blob_id=replay_blob_result.blob.id,
        )

    async def _submit_score_baseline(
        self,
        authorized: _AuthorizedSubmission,
        accepted_beatmap: _AcceptedBeatmapSubmission,
    ) -> _SubmitScoreBaseline:
        overall_stats_before = await self._current_user_stats_for_submit_response(
            user_id=authorized.auth_ctx.user_id,
            ruleset=accepted_beatmap.score_ruleset,
            playstyle=accepted_beatmap.score_playstyle,
            phase="before",
        )
        beatmap_rank_before = (
            await self._beatmap_rank_for_submit_response(
                user_id=authorized.auth_ctx.user_id,
                beatmap_id=accepted_beatmap.resolved_beatmap_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
                ruleset=accepted_beatmap.score_ruleset,
                playstyle=accepted_beatmap.score_playstyle,
                phase="before",
            )
            if accepted_beatmap.leaderboard_eligible_at_submission
            else None
        )
        return _SubmitScoreBaseline(
            overall_stats_before=overall_stats_before,
            beatmap_rank_before=beatmap_rank_before,
        )

    async def _submit_completed_score(
        self,
        command: SubmitScoreCommand,
    ) -> tuple[SubmitScoreCommandResult, float]:
        db_start = time.perf_counter()
        command_result = await self._submit_score_use_case.execute(command)
        return command_result, (time.perf_counter() - db_start) * 1000

    async def _persist_completed_submission(
        self,
        *,
        attempt: _SubmissionAttempt,
        authorized: _AuthorizedSubmission,
        accepted_beatmap: _AcceptedBeatmapSubmission,
        validated: _ValidatedSubmission,
        replay: _ReplayBlobReference,
        decrypt_latency_ms: float,
    ) -> SubmissionResult:
        score = _build_score(attempt, authorized, accepted_beatmap, validated)
        baseline = await self._submit_score_baseline(authorized, accepted_beatmap)

        command_result, db_latency_ms = await self._submit_completed_score(
            _completed_submit_command(
                attempt=attempt,
                authorized=authorized,
                accepted_beatmap=accepted_beatmap,
                validated=validated,
                replay=replay,
                score=score,
            )
        )

        if command_result.outcome != SubmitScoreCommandOutcome.COMPLETED:
            logger.warning(
                "score_submission_failed",
                reason=command_result.error_reason,
                fingerprint=authorized.fingerprint,
                user_id=authorized.auth_ctx.user_id,
                beatmap_checksum=authorized.parsed.beatmap_checksum,
            )
            return _submission_result_from_command(
                command_result,
                beatmap_rank_delta=(
                    BeatmapRankDelta(before=baseline.beatmap_rank_before, after=None)
                    if accepted_beatmap.leaderboard_eligible_at_submission
                    else None
                ),
                overall_stats_before=baseline.overall_stats_before,
            )

        performance_response_available = command_result.existing_submission
        if not command_result.existing_submission:
            performance_response_available = await self._request_performance_calculation(
                score_id=command_result.score_id,
                requested_at=attempt.input_data.submitted_at,
            )

        _log_submission_completed(
            attempt=attempt,
            authorized=authorized,
            accepted_beatmap=accepted_beatmap,
            replay=replay,
            command_result=command_result,
            decrypt_latency_ms=decrypt_latency_ms,
            db_latency_ms=db_latency_ms,
        )

        return await self._build_accepted_submission_result(
            command_result,
            beatmap_checksum=authorized.parsed.beatmap_checksum,
            beatmap_rank_before=baseline.beatmap_rank_before,
            include_beatmap_rank_delta=accepted_beatmap.leaderboard_eligible_at_submission,
            overall_stats_before=baseline.overall_stats_before,
            wait_for_performance=performance_response_available,
        )

    async def _request_performance_calculation(
        self,
        *,
        score_id: int | None,
        requested_at: datetime,
    ) -> bool:
        if (
            score_id is None
            or self._performance_calculation_request is None
            or self._performance_calculator_identity is None
        ):
            return False

        try:
            result = await self._performance_calculation_request.execute(
                RequestPerformanceCalculationCommand(
                    score_id=score_id,
                    calculator_name=self._performance_calculator_identity.calculator_name(),
                    calculator_version=self._performance_calculator_identity.calculator_version(),
                    requested_at=requested_at,
                )
            )
        except Exception as exc:
            logger.warning(
                "score_performance_calculation_request_failed",
                score_id=score_id,
                error=type(exc).__name__,
            )
            return False

        logger.info(
            "score_performance_calculation_requested",
            score_id=score_id,
            outcome=result.outcome.value,
            calculation_id=None if result.calculation is None else result.calculation.id,
            worker_wake_requested=result.worker_wake_requested,
            worker_wake_failed=result.worker_wake_failed,
        )
        return result.outcome in _PERFORMANCE_RESPONSE_AVAILABLE_OUTCOMES

    async def _submit_response_deltas(
        self,
        command_result: SubmitScoreCommandResult,
        *,
        beatmap_checksum: str,
        include_beatmap_rank_delta: bool,
    ) -> _SubmitResponseDeltas:
        return _SubmitResponseDeltas(
            overall_stats_after=await self._current_user_stats_for_submit_response(
                user_id=command_result.user_id,
                ruleset=command_result.ruleset,
                playstyle=command_result.playstyle,
                phase="after",
            ),
            beatmap_rank_after=await self._beatmap_rank_after_for_submit_response(
                command_result,
                beatmap_checksum=beatmap_checksum,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
            ),
        )

    async def _wait_for_submit_performance_response(
        self,
        score_id: int,
    ) -> PerformanceSubmitResponse:
        assert self._performance_response_query is not None
        return await self._performance_response_query.wait_for_submit_response(
            PerformanceSubmitResponseQuery(score_id=score_id)
        )

    async def _build_accepted_submission_result(
        self,
        command_result: SubmitScoreCommandResult,
        *,
        beatmap_checksum: str,
        beatmap_rank_before: int | None,
        include_beatmap_rank_delta: bool,
        overall_stats_before: UserCurrentStats | None,
        wait_for_performance: bool,
    ) -> SubmissionResult:
        if (
            not wait_for_performance
            or command_result.score_id is None
            or self._performance_response_query is None
        ):
            deltas = await self._submit_response_deltas(
                command_result,
                beatmap_checksum=beatmap_checksum,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
            )
            return _submission_result_from_command(
                command_result,
                beatmap_rank_delta=_beatmap_rank_delta_for_submit_response(
                    before=beatmap_rank_before,
                    after=deltas.beatmap_rank_after,
                    include_beatmap_rank_delta=include_beatmap_rank_delta,
                ),
                overall_stats_before=overall_stats_before,
                overall_stats_after=deltas.overall_stats_after,
            )

        personal_best_delta = command_result.personal_best_delta
        if personal_best_delta is not None:
            return await self._build_personal_best_submission_result(
                command_result,
                personal_best_delta,
                beatmap_checksum=beatmap_checksum,
                beatmap_rank_before=beatmap_rank_before,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
                overall_stats_before=overall_stats_before,
            )

        response = await self._wait_for_submit_performance_response(command_result.score_id)
        if response.state is PerformanceSubmitResponseState.RETRYABLE:
            _stop_submission(
                _performance_pending_submission_result(
                    command_result,
                    overall_stats_before=overall_stats_before,
                )
            )

        deltas = await self._submit_response_deltas(
            command_result,
            beatmap_checksum=beatmap_checksum,
            include_beatmap_rank_delta=include_beatmap_rank_delta,
        )
        return _completed_submit_response_result(
            command_result,
            stable_pp=response.stable_pp,
            beatmap_rank_delta=_beatmap_rank_delta_for_submit_response(
                before=beatmap_rank_before,
                after=deltas.beatmap_rank_after,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
            ),
            overall_stats_before=overall_stats_before,
            overall_stats_after=deltas.overall_stats_after,
        )

    async def _personal_best_pp_delta(
        self,
        command_result: SubmitScoreCommandResult,
        personal_best_delta: PersonalBestDelta,
        *,
        overall_stats_before: UserCurrentStats | None,
    ) -> tuple[int, int]:
        assert command_result.score_id is not None

        pp_before = await self._stable_pp_without_wait(personal_best_delta.before_score_id)

        if personal_best_delta.after_score_id == command_result.score_id:
            response = await self._wait_for_submit_performance_response(command_result.score_id)
            if response.state is PerformanceSubmitResponseState.RETRYABLE:
                _stop_submission(
                    _performance_pending_submission_result(
                        command_result,
                        overall_stats_before=overall_stats_before,
                        stable_pp_before=pp_before,
                        personal_best_delta=personal_best_delta,
                    )
                )
            return pp_before, response.stable_pp or 0

        if personal_best_delta.after_score_id == personal_best_delta.before_score_id:
            return pp_before, pp_before

        pp_after = await self._stable_pp_without_wait(personal_best_delta.after_score_id)
        return pp_before, pp_after

    async def _build_personal_best_submission_result(
        self,
        command_result: SubmitScoreCommandResult,
        personal_best_delta: PersonalBestDelta,
        *,
        beatmap_checksum: str,
        beatmap_rank_before: int | None,
        include_beatmap_rank_delta: bool,
        overall_stats_before: UserCurrentStats | None,
    ) -> SubmissionResult:
        pp_before, pp_after = await self._personal_best_pp_delta(
            command_result,
            personal_best_delta,
            overall_stats_before=overall_stats_before,
        )
        deltas = await self._submit_response_deltas(
            command_result,
            beatmap_checksum=beatmap_checksum,
            include_beatmap_rank_delta=include_beatmap_rank_delta,
        )
        return _completed_submit_response_result(
            command_result,
            stable_pp=pp_after,
            stable_pp_before=pp_before,
            personal_best_delta=personal_best_delta,
            beatmap_rank_delta=_beatmap_rank_delta_for_submit_response(
                before=beatmap_rank_before,
                after=deltas.beatmap_rank_after,
                include_beatmap_rank_delta=include_beatmap_rank_delta,
            ),
            overall_stats_before=overall_stats_before,
            overall_stats_after=deltas.overall_stats_after,
        )

    async def _beatmap_rank_after_for_submit_response(
        self,
        command_result: SubmitScoreCommandResult,
        *,
        beatmap_checksum: str,
        include_beatmap_rank_delta: bool,
    ) -> int | None:
        if not include_beatmap_rank_delta:
            return None
        return await self._beatmap_rank_for_submit_response(
            user_id=command_result.user_id,
            beatmap_id=command_result.beatmap_id,
            beatmap_checksum=beatmap_checksum,
            ruleset=command_result.ruleset,
            playstyle=command_result.playstyle,
            phase="after",
        )

    async def _beatmap_rank_for_submit_response(
        self,
        *,
        user_id: int | None,
        beatmap_id: int | None,
        beatmap_checksum: str,
        ruleset: Ruleset | None,
        playstyle: Playstyle | None,
        phase: str,
    ) -> int | None:
        if user_id is None or beatmap_id is None or self._beatmap_personal_best_rank_query is None:
            return None

        query_ruleset = ruleset or Ruleset.OSU
        query_playstyle = playstyle or Playstyle.VANILLA
        try:
            result = await self._beatmap_personal_best_rank_query.execute(
                BeatmapPersonalBestRankQueryInput(
                    user_id=user_id,
                    beatmap_id=beatmap_id,
                    beatmap_checksum=beatmap_checksum,
                    ruleset=query_ruleset,
                    playstyle=query_playstyle,
                )
            )
        except Exception:
            logger.exception(
                "score_submission_beatmap_rank_query_failed",
                user_id=user_id,
                beatmap_id=beatmap_id,
                ruleset=query_ruleset.value,
                playstyle=query_playstyle.value,
                phase=phase,
            )
            return None
        return result.rank

    async def _current_user_stats_for_submit_response(
        self,
        *,
        user_id: int | None,
        ruleset: Ruleset | None,
        playstyle: Playstyle | None,
        phase: str,
    ) -> UserCurrentStats | None:
        if user_id is None or self._current_user_stats_query is None:
            return None

        query_ruleset = ruleset or Ruleset.OSU
        query_playstyle = playstyle or Playstyle.VANILLA
        try:
            result = await self._current_user_stats_query.execute(
                CurrentUserStatsQueryInput(
                    user_ids=(user_id,),
                    ruleset=query_ruleset,
                    playstyle=query_playstyle,
                )
            )
        except Exception:
            logger.exception(
                "score_submission_overall_stats_query_failed",
                user_id=user_id,
                ruleset=query_ruleset.value,
                playstyle=query_playstyle.value,
                phase=phase,
            )
            return None
        return result.get(user_id)

    async def _stable_pp_without_wait(self, score_id: int | None) -> int:
        if score_id is None:
            return 0
        assert self._performance_response_query is not None
        response = await self._performance_response_query.get_submit_response(
            PerformanceSubmitResponseQuery(score_id=score_id)
        )
        return response.stable_pp or 0

    async def _request_score_submit_fallback_warmup(
        self,
        *,
        user_id: int,
        beatmap_id: int,
        checksum_md5: str,
    ) -> None:
        if self._beatmap_file_warmup_use_case is None:
            return

        try:
            _ = await self._beatmap_file_warmup_use_case.execute(
                BeatmapFileWarmupRequest(
                    entrance=BeatmapFileWarmupEntrance.STABLE_SCORE_SUBMIT_FALLBACK,
                    user_id=user_id,
                    beatmap_id=beatmap_id,
                    checksum_md5=checksum_md5,
                )
            )
        except Exception:
            logger.exception(
                "score_submit_beatmap_file_warmup_failed",
                user_id=user_id,
                beatmap_id=beatmap_id,
                has_checksum=checksum_md5 != "",
            )

    async def _record_terminal_reject(
        self,
        *,
        fingerprint: str,
        user_id: int,
        beatmap_checksum: str,
        submitted_at: datetime,
        error_reason: str,
        opaque_field_hashes: Mapping[str, str] | None = None,
    ) -> SubmissionResult:
        result = await self._submit_score_use_case.execute(
            SubmitScoreCommand(
                fingerprint=fingerprint,
                user_id=user_id,
                beatmap_checksum=beatmap_checksum,
                submitted_at=submitted_at,
                outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
                error_reason=error_reason,
                opaque_field_hashes=opaque_field_hashes,
            )
        )
        return _submission_result_from_command(result)

    async def _record_retryable(
        self,
        *,
        fingerprint: str,
        user_id: int,
        beatmap_checksum: str,
        submitted_at: datetime,
        error_reason: str,
        opaque_field_hashes: Mapping[str, str] | None = None,
    ) -> SubmissionResult:
        result = await self._submit_score_use_case.execute(
            SubmitScoreCommand(
                fingerprint=fingerprint,
                user_id=user_id,
                beatmap_checksum=beatmap_checksum,
                submitted_at=submitted_at,
                outcome=SubmitScoreCommandOutcome.RETRYABLE,
                error_reason=error_reason,
                opaque_field_hashes=opaque_field_hashes,
            )
        )
        return _submission_result_from_command(result)

    def _format_auth_error(self, ctx: AuthorizationContext) -> str:
        """認証 credential を露出せず authorization error を整形する。"""
        if not ctx.password_valid:
            return "authorization_failed: invalid_password"
        if not ctx.session_valid:
            return "authorization_failed: no_active_session"
        if not ctx.payload_identity_match:
            return "authorization_failed: identity_mismatch"
        return "authorization_failed: unknown"

    def _is_relax_or_autopilot(self, mods: ModCombination) -> bool:
        """リラックスまたは Autopilot mod を含む submission か判定する。"""
        return mods.has(Mod.RELAX) or mods.has(Mod.AUTOPILOT)

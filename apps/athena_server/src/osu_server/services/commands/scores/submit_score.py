"""score submissionの永続化とidempotency結果を扱うcommand use-caseを定義する."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, cast

from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.personal_best import (
    LeaderboardCategory,
    PersonalBestDelta,
)
from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
from osu_server.domain.scores.user_stats import UserStatsPolicy
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBest,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.services.commands.scores.user_stats_projection import (
    replace_current_user_stats_projection,
)

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork, UnitOfWorkFactory

_STATE_PROCESSING = ScoreSubmissionState.PROCESSING
_STATE_COMPLETED = ScoreSubmissionState.COMPLETED
_STATE_TERMINAL_REJECTED = ScoreSubmissionState.TERMINAL_REJECTED
_STATE_RETRYABLE = ScoreSubmissionState.RETRYABLE


class SubmitScoreCommandOutcome(Enum):
    """durableなscore submission commandの結果種別を表す.

    Attributes:
        COMPLETED (str): scoreと関連projectionの永続化が完了した状態.
        TERMINAL_REJECTED (str): 再試行しても成功しない理由で拒否した状態.
        RETRYABLE (str): 後続の再試行で成功する可能性がある失敗状態.
        ACCEPTED_PENDING (str): 同一fingerprintの処理がまだ完了していない状態.
    """

    COMPLETED = "completed"
    TERMINAL_REJECTED = "terminal_rejected"
    RETRYABLE = "retryable"
    ACCEPTED_PENDING = "accepted_pending"


@dataclass(frozen=True, slots=True)
class SubmitScoreCommand:
    """一つのdurable score submission結果を記録するcommand入力を表す.

    Attributes:
        fingerprint (str): idempotency recordを一意に識別するfingerprint.
        user_id (int): scoreを提出したuserのID.
        beatmap_checksum (str): 提出時に検証したbeatmap checksum.
        submitted_at (datetime): scoreを提出した時刻.
        outcome (SubmitScoreCommandOutcome): 記録するsubmissionの終了状態.
        score (Score | None): COMPLETED時に永続化するscore.
        beatmap_id (int | None): response snapshotへ保存するbeatmap ID.
        beatmapset_id (int | None): response snapshotへ保存するbeatmapset ID.
        beatmap_approved_at (datetime | None): 提出時点のbeatmap承認時刻.
        error_reason (str | None): 拒否またはretryable結果を説明するmachine-readableな理由.
        replay_blob_id (int | None): replayを保存済みのblob ID.
        replay_checksum_sha256 (str | None): replay contentのSHA-256 checksum.
        replay_byte_size (int | None): replay contentのbyte数.
        grade_discrepancy (Mapping[str, str] | None): client gradeとの差異を表す診断情報.
        opaque_field_hashes (Mapping[str, str] | None): 保存しないwire fieldのhash診断情報.
        include_personal_best_delta (bool): response snapshotへpersonal best差分を含めるか.
        update_personal_best (bool): leaderboard projectionを更新するか.
        personal_best_category (LeaderboardCategory): personal best比較に使うcategory.
    """

    fingerprint: str
    user_id: int
    beatmap_checksum: str
    submitted_at: datetime
    outcome: SubmitScoreCommandOutcome
    score: Score | None = None
    beatmap_id: int | None = None
    beatmapset_id: int | None = None
    beatmap_approved_at: datetime | None = None
    error_reason: str | None = None
    replay_blob_id: int | None = None
    replay_checksum_sha256: str | None = None
    replay_byte_size: int | None = None
    grade_discrepancy: Mapping[str, str] | None = None
    opaque_field_hashes: Mapping[str, str] | None = None
    include_personal_best_delta: bool = False
    update_personal_best: bool = False
    personal_best_category: LeaderboardCategory = LeaderboardCategory.GLOBAL


@dataclass(frozen=True, slots=True)
class SubmitScoreCommandResult:
    """score submission command実行後にtransportへ返す結果を表す.

    Attributes:
        outcome (SubmitScoreCommandOutcome): 実行後のsubmission結果種別.
        user_id (int | None): 対象userのID.
        ruleset (Ruleset | None): 永続化したscoreのruleset.
        playstyle (Playstyle | None): 永続化したscoreのplaystyle.
        score_id (int | None): 永続化したscoreのID.
        beatmap_id (int | None): 結果が対応するbeatmap ID.
        beatmapset_id (int | None): 結果が対応するbeatmapset ID.
        score (int | None): 永続化したscore値.
        max_combo (int | None): 永続化した最大combo.
        accuracy (float | None): 永続化したaccuracy.
        passed (bool | None): scoreが譜面を完走したか.
        beatmap_playcount (int | None): 提出後のbeatmap play count.
        beatmap_passcount (int | None): 提出後のbeatmap pass count.
        beatmap_approved_at (datetime | None): 提出時点のbeatmap承認時刻.
        replay_attachment_id (int | None): 新規に保存したreplay attachment ID.
        error_reason (str | None): 拒否またはretryable結果の理由.
        existing_submission (bool): 既存idempotency recordから復元した結果か.
        personal_best_delta (PersonalBestDelta | None): leaderboard更新前後のpersonal best差分.
    """

    outcome: SubmitScoreCommandOutcome
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
    replay_attachment_id: int | None = None
    error_reason: str | None = None
    existing_submission: bool = False
    personal_best_delta: PersonalBestDelta | None = None


class SubmitScoreUseCase:
    """一つのscore submission結果をcommand Unit of Work境界で永続化する.

    Attributes:
        _unit_of_work_factory (UnitOfWorkFactory): command transactionを開始するfactory.
        _user_stats_policy (UserStatsPolicy): current UserStats projectionを集計するpolicy.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        user_stats_policy: UserStatsPolicy | None = None,
    ) -> None:
        """Score submission永続化に必要なfactoryとstats policyを保持する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): command transactionを開始するfactory.
            user_stats_policy (UserStatsPolicy | None): current UserStats集計に使うpolicy.
                Noneの場合は既定のUserStatsPolicyを使用する.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._user_stats_policy: UserStatsPolicy = user_stats_policy or UserStatsPolicy()

    async def execute(self, command: SubmitScoreCommand) -> SubmitScoreCommandResult:
        """一つのscore submission結果をdurableな整合性境界で記録する.

        Args:
            command (SubmitScoreCommand): idempotency情報と記録するsubmission結果を持つcommand.

        Returns:
            SubmitScoreCommandResult: 新規または既存idempotency recordに対応する結果.

        Raises:
            ValueError: outcomeに必要なscoreまたはerror reasonまたはreplay metadataが不足する場合.
                または新規outcomeがunsupportedの場合. またはfingerprint競合を再確認しても
                既存submission recordが見つからない場合.
            RuntimeError: completed scoreまたはreplayの永続化collaboratorが失敗を伝播した場合.

        Notes:
            同じfingerprintが既に存在する場合は永続状態を変更せず既存結果を返す.
        """
        async with self._unit_of_work_factory() as uow:
            existing_submission = await uow.submissions.get_by_fingerprint(command.fingerprint)
            if existing_submission is not None:
                return _result_from_existing_submission(existing_submission)

            try:
                active_submission = await uow.submissions.create(
                    ScoreSubmission(
                        id=None,
                        fingerprint=command.fingerprint,
                        user_id=command.user_id,
                        beatmap_checksum=command.beatmap_checksum,
                        submitted_at=command.submitted_at,
                        state=_STATE_PROCESSING,
                        result_snapshot=None,
                    )
                )
            except ValueError:
                raced_submission = await uow.submissions.get_by_fingerprint(command.fingerprint)
                if raced_submission is not None:
                    return _result_from_existing_submission(raced_submission)
                raise

            if command.outcome == SubmitScoreCommandOutcome.TERMINAL_REJECTED:
                result = await _record_terminal_reject(uow, active_submission, command)
                await uow.commit()
                return result

            if command.outcome == SubmitScoreCommandOutcome.RETRYABLE:
                result = await _record_retryable(uow, active_submission, command)
                await uow.commit()
                return result

            if command.outcome != SubmitScoreCommandOutcome.COMPLETED:
                msg = f"unsupported new submission outcome: {command.outcome.value}"
                raise ValueError(msg)

            result = await _record_completed(
                uow,
                active_submission,
                command,
                user_stats_policy=self._user_stats_policy,
            )
            await uow.commit()
            return result


async def _record_completed(
    uow: UnitOfWork,
    submission: ScoreSubmission,
    command: SubmitScoreCommand,
    *,
    user_stats_policy: UserStatsPolicy,
) -> SubmitScoreCommandResult:
    """COMPLETED score submissionを永続化し重複時はterminal rejectへ変換する.

    Args:
        uow (UnitOfWork): 呼び出し側が所有するcommand Unit of Work.
        submission (ScoreSubmission): PROCESSING状態で作成済みのidempotency record.
        command (SubmitScoreCommand): 永続化するCOMPLETED結果を持つcommand.
        user_stats_policy (UserStatsPolicy): current UserStats projectionを再計算するpolicy.

    Returns:
        SubmitScoreCommandResult: completed結果またはduplicate検出時のterminal rejected結果.

    Raises:
        ValueError: completed scoreまたはreplay metadataまたはsubmission IDが不足する場合.
        RuntimeError: scoreまたはreplayの永続化collaboratorが失敗を伝播した場合.
    """
    score = _require_completed_score(command)

    existing_score = await uow.scores.get_by_online_checksum(score.online_checksum)
    if existing_score is not None:
        duplicate_command = SubmitScoreCommand(
            fingerprint=command.fingerprint,
            user_id=command.user_id,
            beatmap_checksum=command.beatmap_checksum,
            submitted_at=command.submitted_at,
            outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
            error_reason="duplicate_online_checksum",
            opaque_field_hashes=command.opaque_field_hashes,
        )
        return await _record_terminal_reject(uow, submission, duplicate_command)

    replay_checksum = command.replay_checksum_sha256
    if replay_checksum is not None and await uow.replays.exists_by_checksum(replay_checksum):
        duplicate_command = SubmitScoreCommand(
            fingerprint=command.fingerprint,
            user_id=command.user_id,
            beatmap_checksum=command.beatmap_checksum,
            submitted_at=command.submitted_at,
            outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
            error_reason="duplicate_replay_checksum",
            opaque_field_hashes=command.opaque_field_hashes,
        )
        return await _record_terminal_reject(uow, submission, duplicate_command)

    created_score = await uow.scores.create(score)
    assert created_score.id is not None, "Score ID must be set after creation"

    created_replay = None
    if replay_checksum is not None:
        replay_blob_id = _require_replay_blob_id(command)
        replay_byte_size = _require_replay_byte_size(command)
        created_replay = await uow.replays.create(
            Replay(
                id=None,
                score_id=created_score.id,
                blob_id=replay_blob_id,
                checksum_sha256=replay_checksum,
                byte_size=replay_byte_size,
            )
        )

    personal_best_delta = await _submit_personal_best_delta(
        uow,
        command=command,
        created_score=created_score,
    )
    beatmap_submission_counts = await uow.beatmaps.increment_submission_counts(
        created_score.beatmap_id,
        passed=created_score.passed,
    )
    _ = await replace_current_user_stats_projection(
        uow,
        user_id=created_score.user_id,
        ruleset=created_score.ruleset,
        playstyle=created_score.playstyle,
        policy=user_stats_policy,
    )

    completion_snapshot = _completion_snapshot(
        command,
        created_score,
        personal_best_delta,
        beatmap_playcount=beatmap_submission_counts.play_count,
        beatmap_passcount=beatmap_submission_counts.pass_count,
    )
    if created_replay is not None:
        assert created_replay.id is not None, "Replay ID must be set after creation"
        completion_snapshot["replay_attachment_id"] = created_replay.id
        completion_snapshot["replay_blob_id"] = created_replay.blob_id

    submission_id = _require_submission_id(submission)
    await uow.submissions.update_state(
        submission_id,
        _STATE_COMPLETED,
        completion_snapshot,
    )
    return SubmitScoreCommandResult(
        outcome=SubmitScoreCommandOutcome.COMPLETED,
        user_id=command.user_id,
        ruleset=created_score.ruleset,
        playstyle=created_score.playstyle,
        score_id=created_score.id,
        beatmap_id=completion_snapshot["beatmap_id"]
        if isinstance(completion_snapshot["beatmap_id"], int)
        else None,
        beatmapset_id=completion_snapshot["beatmapset_id"]
        if isinstance(completion_snapshot["beatmapset_id"], int)
        else None,
        score=created_score.score,
        max_combo=created_score.max_combo,
        accuracy=created_score.accuracy,
        passed=created_score.passed,
        beatmap_playcount=beatmap_submission_counts.play_count,
        beatmap_passcount=beatmap_submission_counts.pass_count,
        beatmap_approved_at=command.beatmap_approved_at,
        replay_attachment_id=created_replay.id if created_replay is not None else None,
        personal_best_delta=personal_best_delta,
    )


async def _record_terminal_reject(
    uow: UnitOfWork,
    submission: ScoreSubmission,
    command: SubmitScoreCommand,
) -> SubmitScoreCommandResult:
    """Terminal reject結果をidempotency recordへ記録する.

    Args:
        uow (UnitOfWork): 呼び出し側が所有するcommand Unit of Work.
        submission (ScoreSubmission): 更新対象のidempotency record.
        command (SubmitScoreCommand): reject理由を持つcommand.

    Returns:
        SubmitScoreCommandResult: terminal rejected状態の結果.

    Raises:
        ValueError: error reasonまたはsubmission IDが不足する場合.
    """
    error_reason = _require_error_reason(command)
    submission_id = _require_submission_id(submission)
    await uow.submissions.update_state(
        submission_id,
        _STATE_TERMINAL_REJECTED,
        _error_snapshot(error_reason, command.opaque_field_hashes),
    )
    return SubmitScoreCommandResult(
        outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
        user_id=command.user_id,
        error_reason=error_reason,
    )


async def _record_retryable(
    uow: UnitOfWork,
    submission: ScoreSubmission,
    command: SubmitScoreCommand,
) -> SubmitScoreCommandResult:
    """retryable結果をidempotency recordへ記録する.

    Args:
        uow (UnitOfWork): 呼び出し側が所有するcommand Unit of Work.
        submission (ScoreSubmission): 更新対象のidempotency record.
        command (SubmitScoreCommand): retryable理由を持つcommand.

    Returns:
        SubmitScoreCommandResult: retryable状態の結果.

    Raises:
        ValueError: error reasonまたはsubmission IDが不足する場合.
    """
    error_reason = _require_error_reason(command)
    submission_id = _require_submission_id(submission)
    await uow.submissions.update_state(
        submission_id,
        _STATE_RETRYABLE,
        _error_snapshot(error_reason, command.opaque_field_hashes),
    )
    return SubmitScoreCommandResult(
        outcome=SubmitScoreCommandOutcome.RETRYABLE,
        user_id=command.user_id,
        error_reason=error_reason,
    )


def _result_from_existing_submission(submission: ScoreSubmission) -> SubmitScoreCommandResult:
    """既存idempotency recordからclientへ返せる安全な結果を復元する.

    Args:
        submission (ScoreSubmission): 処理済みまたは処理中の既存idempotency record.

    Returns:
        SubmitScoreCommandResult: recordのstateとsnapshotから復元した結果.

    Notes:
        不正または欠落したsnapshot fieldはNoneまたは安全な既定reasonへ変換する.
    """
    if submission.state in {_STATE_PROCESSING, ScoreSubmissionState.RECEIVED}:
        return SubmitScoreCommandResult(
            outcome=SubmitScoreCommandOutcome.ACCEPTED_PENDING,
            user_id=submission.user_id,
            error_reason="accepted_pending",
        )

    snapshot = submission.result_snapshot or {}
    if submission.state == _STATE_COMPLETED:
        score_id = _snapshot_int(snapshot.get("score_id"))
        ruleset = _snapshot_ruleset(snapshot.get("ruleset"))
        playstyle = _snapshot_playstyle(snapshot.get("playstyle"))
        beatmap_id = _snapshot_int(snapshot.get("beatmap_id"))
        beatmapset_id = _snapshot_int(snapshot.get("beatmapset_id"))
        score = _snapshot_int(snapshot.get("score"))
        max_combo = _snapshot_int(snapshot.get("max_combo"))
        accuracy = _snapshot_float(snapshot.get("accuracy"))
        passed = snapshot.get("passed")
        beatmap_playcount = _snapshot_int(snapshot.get("beatmap_playcount"))
        beatmap_passcount = _snapshot_int(snapshot.get("beatmap_passcount"))
        beatmap_approved_at = _snapshot_datetime(snapshot.get("beatmap_approved_at"))
        personal_best_delta = _snapshot_personal_best_delta(snapshot.get("personal_best_delta"))
        if score_id is not None:
            return SubmitScoreCommandResult(
                outcome=SubmitScoreCommandOutcome.COMPLETED,
                user_id=submission.user_id,
                ruleset=ruleset,
                playstyle=playstyle,
                score_id=score_id,
                beatmap_id=beatmap_id,
                beatmapset_id=beatmapset_id,
                score=score,
                max_combo=max_combo,
                accuracy=accuracy,
                passed=passed if isinstance(passed, bool) else None,
                beatmap_playcount=beatmap_playcount,
                beatmap_passcount=beatmap_passcount,
                beatmap_approved_at=beatmap_approved_at,
                personal_best_delta=personal_best_delta,
                existing_submission=True,
            )

    error_reason = snapshot.get("error_reason")
    if submission.state == _STATE_RETRYABLE:
        return SubmitScoreCommandResult(
            outcome=SubmitScoreCommandOutcome.RETRYABLE,
            user_id=submission.user_id,
            error_reason=error_reason if isinstance(error_reason, str) else "retryable",
            existing_submission=True,
        )

    return SubmitScoreCommandResult(
        outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
        user_id=submission.user_id,
        error_reason=error_reason if isinstance(error_reason, str) else "terminal_rejected",
        existing_submission=True,
    )


def _snapshot_int(value: object) -> int | None:
    """snapshot値をboolと区別したintへ安全に変換する.

    Args:
        value (object): idまたはcountとして復元するsnapshot値.

    Returns:
        int | None: bool以外のintならその値. それ以外はNone.
    """
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _snapshot_float(value: object) -> float | None:
    """snapshot値をboolと区別したfloatへ安全に変換する.

    Args:
        value (object): accuracyなどの実数として復元するsnapshot値.

    Returns:
        float | None: bool以外のintまたはfloatをfloat化した値. それ以外はNone.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _snapshot_datetime(value: object) -> datetime | None:
    """ISO 8601文字列のsnapshot値をdatetimeへ安全に変換する.

    Args:
        value (object): datetimeとして復元するsnapshot値.

    Returns:
        datetime | None: 有効なISO 8601文字列から復元したdatetime. それ以外はNone.
    """
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _snapshot_ruleset(value: object) -> Ruleset | None:
    """snapshot値をboolと区別したRulesetへ安全に変換する.

    Args:
        value (object): ruleset valueとして復元するsnapshot値.

    Returns:
        Ruleset | None: 既知のRuleset valueなら対応するenum. それ以外はNone.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            return Ruleset(value)
        except ValueError:
            return None
    return None


def _snapshot_playstyle(value: object) -> Playstyle | None:
    """snapshot値をboolと区別したPlaystyleへ安全に変換する.

    Args:
        value (object): playstyle valueとして復元するsnapshot値.

    Returns:
        Playstyle | None: 既知のPlaystyle valueなら対応するenum. それ以外はNone.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            return Playstyle(value)
        except ValueError:
            return None
    return None


def _completion_snapshot(
    command: SubmitScoreCommand,
    created_score: Score,
    personal_best_delta: PersonalBestDelta | None,
    *,
    beatmap_playcount: int,
    beatmap_passcount: int,
) -> dict[str, object]:
    """Completed submissionを再利用可能な結果snapshotへ変換する.

    Args:
        command (SubmitScoreCommand): response snapshotへ保存するsubmission command.
        created_score (Score): 新規に永続化したscore.
        personal_best_delta (PersonalBestDelta | None): 更新前後のpersonal best差分.
        beatmap_playcount (int): 提出後のbeatmap play count.
        beatmap_passcount (int): 提出後のbeatmap pass count.

    Returns:
        dict[str, object]: idempotency recordに保存するJSON互換の結果snapshot.
    """
    beatmap_id = command.beatmap_id if command.beatmap_id is not None else created_score.beatmap_id
    beatmapset_id = command.beatmapset_id if command.beatmapset_id is not None else 0
    completion_snapshot: dict[str, object] = {
        "score_id": created_score.id,
        "beatmap_id": beatmap_id,
        "beatmapset_id": beatmapset_id,
        "score": created_score.score,
        "ruleset": created_score.ruleset.value,
        "playstyle": created_score.playstyle.value,
        "max_combo": created_score.max_combo,
        "accuracy": created_score.accuracy,
        "passed": created_score.passed,
        "beatmap_playcount": beatmap_playcount,
        "beatmap_passcount": beatmap_passcount,
        "beatmap_status_at_submission": (
            created_score.beatmap_status_at_submission.value
            if created_score.beatmap_status_at_submission is not None
            else None
        ),
    }
    if command.beatmap_approved_at is not None:
        completion_snapshot["beatmap_approved_at"] = command.beatmap_approved_at.isoformat()
    if command.grade_discrepancy is not None:
        completion_snapshot["grade_discrepancy"] = dict(command.grade_discrepancy)
    if command.opaque_field_hashes:
        completion_snapshot["opaque_fields"] = dict(command.opaque_field_hashes)
    if personal_best_delta is not None:
        completion_snapshot["personal_best_delta"] = _personal_best_delta_snapshot(
            personal_best_delta
        )
    return completion_snapshot


async def _submit_personal_best_delta(
    uow: UnitOfWork,
    *,
    command: SubmitScoreCommand,
    created_score: Score,
) -> PersonalBestDelta | None:
    """scoreをpersonal best projectionへ反映し必要なら差分を作る.

    Args:
        uow (UnitOfWork): 呼び出し側が所有するcommand Unit of Work.
        command (SubmitScoreCommand): personal best更新方針を含むsubmission command.
        created_score (Score): 新規に永続化したscore.

    Returns:
        PersonalBestDelta | None: 差分を要求した場合の更新前後の値. それ以外はNone.

    Notes:
        未完走またはsubmission時点でleaderboard対象外のscoreは更新も差分作成もしない.
    """
    if not _can_use_score_for_personal_best(created_score):
        return None

    scope = _leaderboard_user_scope(command, created_score)
    if command.update_personal_best:
        await uow.beatmap_leaderboards.lock_scope(scope)
    before_score = (
        await _current_global_leaderboard_best_score(uow, scope)
        if command.include_personal_best_delta
        else None
    )
    after_score = before_score
    updated = False

    if command.update_personal_best:
        _ = await _upsert_mod_leaderboard_best(
            uow,
            command=command,
            created_score=created_score,
        )
        if command.include_personal_best_delta:
            after_score = await _current_global_leaderboard_best_score(uow, scope)
        updated = after_score is not None and after_score.id == created_score.id

    if not command.include_personal_best_delta:
        return None

    return _personal_best_delta_from_scores(
        before_score=before_score,
        after_score=after_score,
        updated=updated,
    )


async def _upsert_mod_leaderboard_best(
    uow: UnitOfWork,
    *,
    command: SubmitScoreCommand,
    created_score: Score,
) -> BeatmapLeaderboardUserBest:
    """scoreのmod scopeにおけるuser bestを必要な場合だけ更新する.

    Args:
        uow (UnitOfWork): 呼び出し側が所有するcommand Unit of Work.
        command (SubmitScoreCommand): scopeを決めるsubmission command.
        created_score (Score): user best候補として永続化したscore.

    Returns:
        BeatmapLeaderboardUserBest: 更新後または既存のmod-scoped user best.
    """
    assert created_score.id is not None
    rank_key = ScoreRankKey(
        score=created_score.score,
        submitted_at=created_score.submitted_at,
        score_id=created_score.id,
    )
    return await uow.beatmap_leaderboards.upsert_if_better(
        UpsertBeatmapLeaderboardUserBest(
            scope=_leaderboard_mod_scope(command, created_score),
            score_id=created_score.id,
            rank_key=rank_key,
        )
    )


async def _current_global_leaderboard_best_score(
    uow: UnitOfWork,
    scope: BeatmapLeaderboardUserScope,
) -> Score | None:
    """指定scopeのglobal mod集合をまたぐuser best scoreを取得する.

    Args:
        uow (UnitOfWork): 呼び出し側が所有するcommand Unit of Work.
        scope (BeatmapLeaderboardUserScope): userとbeatmapとrulesetとplaystyleのscope.

    Returns:
        Score | None: best scoreが存在する場合はそのscore. 存在しない場合はNone.
    """
    best = await uow.beatmap_leaderboards.get_global_user_best(scope)
    if best is None:
        return None
    return await uow.scores.get_by_id(best.score_id)


def _leaderboard_user_scope(
    command: SubmitScoreCommand,
    score: Score,
) -> BeatmapLeaderboardUserScope:
    """Submission commandとscoreからmod非依存のleaderboard user scopeを作る.

    Args:
        command (SubmitScoreCommand): scopeのuser IDを提供するsubmission command.
        score (Score): scopeのbeatmapとrulesetとplaystyleを提供するscore.

    Returns:
        BeatmapLeaderboardUserScope: global user best検索に使うmod非依存scope.
    """
    return BeatmapLeaderboardUserScope(
        user_id=command.user_id,
        beatmap_id=score.beatmap_id,
        beatmap_checksum=score.beatmap_checksum,
        ruleset=score.ruleset,
        playstyle=score.playstyle,
    )


def _leaderboard_mod_scope(
    command: SubmitScoreCommand,
    score: Score,
) -> BeatmapLeaderboardUserBestScope:
    """Submission commandとscoreからmod依存のleaderboard user best scopeを作る.

    Args:
        command (SubmitScoreCommand): scopeのuser IDを提供するsubmission command.
        score (Score): scopeのbeatmapとrulesetとplaystyleとmodsを提供するscore.

    Returns:
        BeatmapLeaderboardUserBestScope: mod-scoped user best更新に使うscope.
    """
    return BeatmapLeaderboardUserBestScope(
        user_id=command.user_id,
        beatmap_id=score.beatmap_id,
        beatmap_checksum=score.beatmap_checksum,
        ruleset=score.ruleset,
        playstyle=score.playstyle,
        mods=score.mods,
    )


def _can_use_score_for_personal_best(score: Score) -> bool:
    """scoreがpersonal bestとleaderboard projectionの候補か判定する.

    Args:
        score (Score): 候補として検査する永続化済みscore.

    Returns:
        bool: scoreがpassedかつsubmission時点でleaderboard対象ならTrue.
    """
    return score.passed and score.leaderboard_eligible_at_submission


def _personal_best_delta_from_scores(
    *,
    before_score: Score | None,
    after_score: Score | None,
    updated: bool,
) -> PersonalBestDelta:
    """Personal best更新前後のscoreをtransport用差分へ変換する.

    Args:
        before_score (Score | None): 更新前のglobal user best score.
        after_score (Score | None): 更新後のglobal user best score.
        updated (bool): 今回のscoreがbestとして採用されたか.

    Returns:
        PersonalBestDelta: 更新前後のscore IDと値および採用結果を持つ差分.
    """
    return PersonalBestDelta(
        before_score_id=before_score.id if before_score is not None else None,
        before_score=before_score.score if before_score is not None else None,
        before_max_combo=before_score.max_combo if before_score is not None else None,
        before_accuracy=before_score.accuracy if before_score is not None else None,
        after_score_id=after_score.id if after_score is not None else None,
        after_score=after_score.score if after_score is not None else None,
        after_max_combo=after_score.max_combo if after_score is not None else None,
        after_accuracy=after_score.accuracy if after_score is not None else None,
        updated=updated,
    )


def _personal_best_delta_snapshot(delta: PersonalBestDelta) -> dict[str, object]:
    """Personal best差分をidempotency snapshotへ保存できるdictへ変換する.

    Args:
        delta (PersonalBestDelta): 保存対象のpersonal best差分.

    Returns:
        dict[str, object]: JSON互換の差分snapshot.
    """
    return {
        "before_score_id": delta.before_score_id,
        "before_score": delta.before_score,
        "before_max_combo": delta.before_max_combo,
        "before_accuracy": delta.before_accuracy,
        "after_score_id": delta.after_score_id,
        "after_score": delta.after_score,
        "after_max_combo": delta.after_max_combo,
        "after_accuracy": delta.after_accuracy,
        "updated": delta.updated,
    }


def _snapshot_personal_best_delta(value: object) -> PersonalBestDelta | None:
    """snapshot値からpersonal best差分を安全に復元する.

    Args:
        value (object): personal best差分として復元するsnapshot値.

    Returns:
        PersonalBestDelta | None: mappingから復元した差分. mapping以外はNone.
    """
    if not isinstance(value, Mapping):
        return None
    snapshot = cast("Mapping[str, object]", value)
    return PersonalBestDelta(
        before_score_id=_snapshot_int(snapshot.get("before_score_id")),
        before_score=_snapshot_int(snapshot.get("before_score")),
        before_max_combo=_snapshot_int(snapshot.get("before_max_combo")),
        before_accuracy=_snapshot_float(snapshot.get("before_accuracy")),
        after_score_id=_snapshot_int(snapshot.get("after_score_id")),
        after_score=_snapshot_int(snapshot.get("after_score")),
        after_max_combo=_snapshot_int(snapshot.get("after_max_combo")),
        after_accuracy=_snapshot_float(snapshot.get("after_accuracy")),
        updated=snapshot.get("updated") is True,
    )


def _error_snapshot(
    error_reason: str,
    opaque_field_hashes: Mapping[str, str] | None,
) -> dict[str, object]:
    """rejectまたはretryable結果をidempotency snapshotへ変換する.

    Args:
        error_reason (str): clientへ返すmachine-readableな失敗理由.
        opaque_field_hashes (Mapping[str, str] | None): 保存しないwire fieldのhash診断情報.

    Returns:
        dict[str, object]: error reasonと任意のopaque field hashを持つsnapshot.
    """
    snapshot: dict[str, object] = {"error_reason": error_reason}
    if opaque_field_hashes:
        snapshot["opaque_fields"] = dict(opaque_field_hashes)
    return snapshot


def _require_completed_score(command: SubmitScoreCommand) -> Score:
    """Completed outcomeに必須のscoreを取得する.

    Args:
        command (SubmitScoreCommand): score fieldを検査するsubmission command.

    Returns:
        Score: commandが持つcompleted score.

    Raises:
        ValueError: command.scoreがNoneの場合.
    """
    if command.score is None:
        msg = "completed score submission command requires score"
        raise ValueError(msg)
    return command.score


def _require_error_reason(command: SubmitScoreCommand) -> str:
    """rejectまたはretryable outcomeに必須のerror reasonを取得する.

    Args:
        command (SubmitScoreCommand): error reason fieldを検査するsubmission command.

    Returns:
        str: commandが持つmachine-readableな失敗理由.

    Raises:
        ValueError: command.error_reasonがNoneの場合.
    """
    if command.error_reason is None:
        msg = f"{command.outcome.value} score submission command requires error_reason"
        raise ValueError(msg)
    return command.error_reason


def _require_replay_blob_id(command: SubmitScoreCommand) -> int:
    """Replay checksumを保存する場合に必須のblob IDを取得する.

    Args:
        command (SubmitScoreCommand): replay metadata fieldを検査するsubmission command.

    Returns:
        int: commandが持つreplay blob ID.

    Raises:
        ValueError: command.replay_blob_idがNoneの場合.
    """
    if command.replay_blob_id is None:
        msg = "replay command requires replay_blob_id when replay_checksum_sha256 is set"
        raise ValueError(msg)
    return command.replay_blob_id


def _require_replay_byte_size(command: SubmitScoreCommand) -> int:
    """Replay checksumを保存する場合に必須のbyte sizeを取得する.

    Args:
        command (SubmitScoreCommand): replay metadata fieldを検査するsubmission command.

    Returns:
        int: commandが持つreplay byte size.

    Raises:
        ValueError: command.replay_byte_sizeがNoneの場合.
    """
    if command.replay_byte_size is None:
        msg = "replay command requires replay_byte_size when replay_checksum_sha256 is set"
        raise ValueError(msg)
    return command.replay_byte_size


def _require_submission_id(submission: ScoreSubmission) -> int:
    """state更新前に必須のidempotency record IDを取得する.

    Args:
        submission (ScoreSubmission): IDの有無を検査するidempotency record.

    Returns:
        int: command repositoryが設定したsubmission ID.

    Raises:
        ValueError: submission.idがNoneの場合.
    """
    if submission.id is None:
        msg = "Submission ID must be set before state update"
        raise ValueError(msg)
    return submission.id

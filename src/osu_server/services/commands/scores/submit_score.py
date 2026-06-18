"""Submit score command use-case."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, cast

from osu_server.domain.scores.leaderboards import (
    ALL_MODS_FILTER_KEY,
    ScoreRankKey,
    projection_keys_for_score,
)
from osu_server.domain.scores.personal_best import (
    LeaderboardCategory,
    PersonalBestDelta,
)
from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.submission import ScoreSubmission
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBest,
    BeatmapLeaderboardUserBestScope,
    UpsertBeatmapLeaderboardUserBest,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.score import Score
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork, UnitOfWorkFactory

_STATE_PROCESSING = "processing"
_STATE_COMPLETED = "completed"
_STATE_TERMINAL_REJECTED = "terminal_rejected"
_STATE_RETRYABLE = "retryable"


class SubmitScoreCommandOutcome(Enum):
    """Durable score submission command outcome."""

    COMPLETED = "completed"
    TERMINAL_REJECTED = "terminal_rejected"
    RETRYABLE = "retryable"
    ACCEPTED_PENDING = "accepted_pending"


@dataclass(frozen=True, slots=True)
class SubmitScoreCommand:
    """Command input for one durable score submission outcome."""

    fingerprint: str
    user_id: int
    beatmap_checksum: str
    submitted_at: datetime
    outcome: SubmitScoreCommandOutcome
    score: Score | None = None
    beatmap_id: int | None = None
    beatmapset_id: int | None = None
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
    """Result of the score submission command use-case."""

    outcome: SubmitScoreCommandOutcome
    score_id: int | None = None
    beatmap_id: int | None = None
    beatmapset_id: int | None = None
    score: int | None = None
    max_combo: int | None = None
    accuracy: float | None = None
    passed: bool | None = None
    replay_attachment_id: int | None = None
    error_reason: str | None = None
    existing_submission: bool = False
    personal_best_delta: PersonalBestDelta | None = None


class SubmitScoreUseCase:
    """Persist one score submission outcome through the command UoW boundary."""

    def __init__(self, *, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory

    async def execute(self, command: SubmitScoreCommand) -> SubmitScoreCommandResult:
        """Execute the command inside one durable consistency boundary."""
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

            result = await _record_completed(uow, active_submission, command)
            await uow.commit()
            return result


async def _record_completed(
    uow: UnitOfWork,
    submission: ScoreSubmission,
    command: SubmitScoreCommand,
) -> SubmitScoreCommandResult:
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

    completion_snapshot = _completion_snapshot(command, created_score, personal_best_delta)
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
        replay_attachment_id=created_replay.id if created_replay is not None else None,
        personal_best_delta=personal_best_delta,
    )


async def _record_terminal_reject(
    uow: UnitOfWork,
    submission: ScoreSubmission,
    command: SubmitScoreCommand,
) -> SubmitScoreCommandResult:
    error_reason = _require_error_reason(command)
    submission_id = _require_submission_id(submission)
    await uow.submissions.update_state(
        submission_id,
        _STATE_TERMINAL_REJECTED,
        _error_snapshot(error_reason, command.opaque_field_hashes),
    )
    return SubmitScoreCommandResult(
        outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
        error_reason=error_reason,
    )


async def _record_retryable(
    uow: UnitOfWork,
    submission: ScoreSubmission,
    command: SubmitScoreCommand,
) -> SubmitScoreCommandResult:
    error_reason = _require_error_reason(command)
    submission_id = _require_submission_id(submission)
    await uow.submissions.update_state(
        submission_id,
        _STATE_RETRYABLE,
        _error_snapshot(error_reason, command.opaque_field_hashes),
    )
    return SubmitScoreCommandResult(
        outcome=SubmitScoreCommandOutcome.RETRYABLE,
        error_reason=error_reason,
    )


def _result_from_existing_submission(submission: ScoreSubmission) -> SubmitScoreCommandResult:
    """Return a client-safe result from an existing idempotency record."""
    if submission.state in {_STATE_PROCESSING, "received"}:
        return SubmitScoreCommandResult(
            outcome=SubmitScoreCommandOutcome.ACCEPTED_PENDING,
            error_reason="accepted_pending",
        )

    snapshot = submission.result_snapshot or {}
    if submission.state == _STATE_COMPLETED:
        score_id = _snapshot_int(snapshot.get("score_id"))
        beatmap_id = _snapshot_int(snapshot.get("beatmap_id"))
        beatmapset_id = _snapshot_int(snapshot.get("beatmapset_id"))
        score = _snapshot_int(snapshot.get("score"))
        max_combo = _snapshot_int(snapshot.get("max_combo"))
        accuracy = _snapshot_float(snapshot.get("accuracy"))
        passed = snapshot.get("passed")
        personal_best_delta = _snapshot_personal_best_delta(snapshot.get("personal_best_delta"))
        if score_id is not None:
            return SubmitScoreCommandResult(
                outcome=SubmitScoreCommandOutcome.COMPLETED,
                score_id=score_id,
                beatmap_id=beatmap_id,
                beatmapset_id=beatmapset_id,
                score=score,
                max_combo=max_combo,
                accuracy=accuracy,
                passed=passed if isinstance(passed, bool) else None,
                personal_best_delta=personal_best_delta,
                existing_submission=True,
            )

    error_reason = snapshot.get("error_reason")
    if submission.state == _STATE_RETRYABLE:
        return SubmitScoreCommandResult(
            outcome=SubmitScoreCommandOutcome.RETRYABLE,
            error_reason=error_reason if isinstance(error_reason, str) else "retryable",
            existing_submission=True,
        )

    return SubmitScoreCommandResult(
        outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
        error_reason=error_reason if isinstance(error_reason, str) else "terminal_rejected",
        existing_submission=True,
    )


def _snapshot_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _snapshot_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _completion_snapshot(
    command: SubmitScoreCommand,
    created_score: Score,
    personal_best_delta: PersonalBestDelta | None,
) -> dict[str, object]:
    beatmap_id = command.beatmap_id if command.beatmap_id is not None else created_score.beatmap_id
    beatmapset_id = command.beatmapset_id if command.beatmapset_id is not None else 0
    completion_snapshot: dict[str, object] = {
        "score_id": created_score.id,
        "beatmap_id": beatmap_id,
        "beatmapset_id": beatmapset_id,
        "score": created_score.score,
        "max_combo": created_score.max_combo,
        "accuracy": created_score.accuracy,
        "passed": created_score.passed,
        "beatmap_status_at_submission": created_score.beatmap_status_at_submission,
    }
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
    if not _can_use_score_for_personal_best(created_score):
        return None

    scope = _all_mods_leaderboard_scope(command, created_score)
    before_score = (
        await _current_leaderboard_best_score(uow, scope)
        if command.include_personal_best_delta
        else None
    )
    after_score = before_score
    updated = False

    if command.update_personal_best:
        all_mods_best = await _upsert_matching_leaderboard_scopes(
            uow,
            command=command,
            created_score=created_score,
        )
        if all_mods_best is not None and command.include_personal_best_delta:
            after_score = await uow.scores.get_by_id(all_mods_best.score_id)
        updated = after_score is not None and after_score.id == created_score.id

    if not command.include_personal_best_delta:
        return None

    return _personal_best_delta_from_scores(
        before_score=before_score,
        after_score=after_score,
        updated=updated,
    )


async def _upsert_matching_leaderboard_scopes(
    uow: UnitOfWork,
    *,
    command: SubmitScoreCommand,
    created_score: Score,
) -> BeatmapLeaderboardUserBest | None:
    assert created_score.id is not None
    rank_key = ScoreRankKey(
        score=created_score.score,
        submitted_at=created_score.submitted_at,
        score_id=created_score.id,
    )
    all_mods_best = None
    for mod_filter_key in projection_keys_for_score(created_score.mods):
        best = await uow.beatmap_leaderboards.upsert_if_better(
            UpsertBeatmapLeaderboardUserBest(
                scope=_leaderboard_scope(command, created_score, mod_filter_key),
                score_id=created_score.id,
                rank_key=rank_key,
            )
        )
        if mod_filter_key is ALL_MODS_FILTER_KEY:
            all_mods_best = best
    return all_mods_best


async def _current_leaderboard_best_score(
    uow: UnitOfWork,
    scope: BeatmapLeaderboardUserBestScope,
) -> Score | None:
    best = await uow.beatmap_leaderboards.get_user_best(scope)
    if best is None:
        return None
    return await uow.scores.get_by_id(best.score_id)


def _all_mods_leaderboard_scope(
    command: SubmitScoreCommand,
    score: Score,
) -> BeatmapLeaderboardUserBestScope:
    return _leaderboard_scope(command, score, ALL_MODS_FILTER_KEY)


def _leaderboard_scope(
    command: SubmitScoreCommand,
    score: Score,
    mod_filter_key: int | None,
) -> BeatmapLeaderboardUserBestScope:
    return BeatmapLeaderboardUserBestScope(
        user_id=command.user_id,
        beatmap_id=score.beatmap_id,
        ruleset=score.ruleset,
        playstyle=score.playstyle,
        mod_filter_key=mod_filter_key,
    )


def _can_use_score_for_personal_best(score: Score) -> bool:
    return score.passed and score.leaderboard_eligible_at_submission


def _personal_best_delta_from_scores(
    *,
    before_score: Score | None,
    after_score: Score | None,
    updated: bool,
) -> PersonalBestDelta:
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
    snapshot: dict[str, object] = {"error_reason": error_reason}
    if opaque_field_hashes:
        snapshot["opaque_fields"] = dict(opaque_field_hashes)
    return snapshot


def _require_completed_score(command: SubmitScoreCommand) -> Score:
    if command.score is None:
        msg = "completed score submission command requires score"
        raise ValueError(msg)
    return command.score


def _require_error_reason(command: SubmitScoreCommand) -> str:
    if command.error_reason is None:
        msg = f"{command.outcome.value} score submission command requires error_reason"
        raise ValueError(msg)
    return command.error_reason


def _require_replay_blob_id(command: SubmitScoreCommand) -> int:
    if command.replay_blob_id is None:
        msg = "replay command requires replay_blob_id when replay_checksum_sha256 is set"
        raise ValueError(msg)
    return command.replay_blob_id


def _require_replay_byte_size(command: SubmitScoreCommand) -> int:
    if command.replay_byte_size is None:
        msg = "replay command requires replay_byte_size when replay_checksum_sha256 is set"
        raise ValueError(msg)
    return command.replay_byte_size


def _require_submission_id(submission: ScoreSubmission) -> int:
    if submission.id is None:
        msg = "Submission ID must be set before state update"
        raise ValueError(msg)
    return submission.id

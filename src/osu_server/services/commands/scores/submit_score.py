"""Submit score command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.submission import ScoreSubmission

if TYPE_CHECKING:
    from collections.abc import Mapping
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


@dataclass(frozen=True, slots=True)
class SubmitScoreCommandResult:
    """Result of the score submission command use-case."""

    outcome: SubmitScoreCommandOutcome
    score_id: int | None = None
    beatmap_id: int | None = None
    beatmapset_id: int | None = None
    replay_attachment_id: int | None = None
    error_reason: str | None = None


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

    completion_snapshot = _completion_snapshot(command, created_score)
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
        replay_attachment_id=created_replay.id if created_replay is not None else None,
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
        score_id = snapshot.get("score_id")
        beatmap_id = snapshot.get("beatmap_id")
        beatmapset_id = snapshot.get("beatmapset_id")
        if isinstance(score_id, int):
            return SubmitScoreCommandResult(
                outcome=SubmitScoreCommandOutcome.COMPLETED,
                score_id=score_id,
                beatmap_id=beatmap_id if isinstance(beatmap_id, int) else None,
                beatmapset_id=beatmapset_id if isinstance(beatmapset_id, int) else None,
            )

    error_reason = snapshot.get("error_reason")
    if submission.state == _STATE_RETRYABLE:
        return SubmitScoreCommandResult(
            outcome=SubmitScoreCommandOutcome.RETRYABLE,
            error_reason=error_reason if isinstance(error_reason, str) else "retryable",
        )

    return SubmitScoreCommandResult(
        outcome=SubmitScoreCommandOutcome.TERMINAL_REJECTED,
        error_reason=error_reason if isinstance(error_reason, str) else "terminal_rejected",
    )


def _completion_snapshot(
    command: SubmitScoreCommand,
    created_score: Score,
) -> dict[str, object]:
    beatmap_id = command.beatmap_id if command.beatmap_id is not None else created_score.beatmap_id
    beatmapset_id = command.beatmapset_id if command.beatmapset_id is not None else 0
    completion_snapshot: dict[str, object] = {
        "score_id": created_score.id,
        "beatmap_id": beatmap_id,
        "beatmapset_id": beatmapset_id,
        "beatmap_status_at_submission": created_score.beatmap_status_at_submission,
    }
    if command.grade_discrepancy is not None:
        completion_snapshot["grade_discrepancy"] = dict(command.grade_discrepancy)
    if command.opaque_field_hashes:
        completion_snapshot["opaque_fields"] = dict(command.opaque_field_hashes)
    return completion_snapshot


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

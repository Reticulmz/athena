"""In-memory command-side score submission repository."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryScoreSubmissionCommandRepository:
    """Submission command repository backed by an active in-memory UoW state."""

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        if submission.fingerprint in self._state.submission_id_by_fingerprint:
            msg = f"fingerprint already exists: {submission.fingerprint}"
            raise ValueError(msg)

        created = replace(submission, id=self._state.next_submission_id)
        assert created.id is not None
        self._state.next_submission_id += 1
        self._state.submissions_by_id[created.id] = created
        self._state.submission_id_by_fingerprint[created.fingerprint] = created.id
        return created

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        submission_id = self._state.submission_id_by_fingerprint.get(fingerprint)
        if submission_id is None:
            return None
        return self._state.submissions_by_id.get(submission_id)

    async def update_state(
        self,
        submission_id: int,
        state: ScoreSubmissionState,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        existing = self._state.submissions_by_id.get(submission_id)
        if existing is None:
            msg = f"Submission not found: {submission_id}"
            raise ValueError(msg)
        self._state.submissions_by_id[submission_id] = replace(
            existing,
            state=state,
            result_snapshot=result_snapshot,
        )

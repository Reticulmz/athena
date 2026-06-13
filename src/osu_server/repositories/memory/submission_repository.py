"""InMemoryScoreSubmissionRepository — dict-based submission repository for testing."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.submission import ScoreSubmission


class InMemoryScoreSubmissionRepository:
    """In-memory implementation of the ScoreSubmissionRepository Protocol.

    Uses plain dicts for storage with auto-incrementing id.
    Not thread-safe — intended for single-threaded test environments only.
    """

    def __init__(self) -> None:
        self._submissions_by_id: dict[int, ScoreSubmission] = {}
        self._id_by_fingerprint: dict[str, int] = {}
        self._next_id: int = 1

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        """Persist a new submission and return it with a generated id.

        Raises ``ValueError`` if ``fingerprint`` already exists.
        """
        if submission.fingerprint in self._id_by_fingerprint:
            msg = f"fingerprint already exists: {submission.fingerprint}"
            raise ValueError(msg)

        created = replace(submission, id=self._next_id)
        self._next_id += 1
        assert created.id is not None

        self._submissions_by_id[created.id] = created
        self._id_by_fingerprint[created.fingerprint] = created.id

        return created

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        """Return submission with *fingerprint*, or ``None`` if not found."""
        submission_id = self._id_by_fingerprint.get(fingerprint)
        if submission_id is None:
            return None
        return self._submissions_by_id.get(submission_id)

    async def update_state(
        self,
        submission_id: int,
        state: str,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        """Update submission state.

        Raises ``ValueError`` if *submission_id* not found.
        """
        submission = self._submissions_by_id.get(submission_id)
        if submission is None:
            msg = f"Submission not found: {submission_id}"
            raise ValueError(msg)

        updated = replace(
            submission,
            state=state,
            result_snapshot=result_snapshot,
        )
        self._submissions_by_id[submission_id] = updated

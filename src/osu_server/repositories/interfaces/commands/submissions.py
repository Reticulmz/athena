"""Command-side score submission repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState


class ScoreSubmissionCommandRepository(Protocol):
    """Mutation and idempotency-check port for score submissions."""

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        """Persist a submission and return it with repository-assigned identity."""
        ...

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        """Return a submission by fingerprint for idempotency checks."""
        ...

    async def update_state(
        self,
        submission_id: int,
        state: ScoreSubmissionState,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        """Persist the processing state and optional result snapshot."""
        ...

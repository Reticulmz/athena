"""ScoreSubmissionRepository Protocol for submission state persistence."""

from typing import Protocol

from osu_server.domain.scores.submission import ScoreSubmission


class ScoreSubmissionRepository(Protocol):
    """Repository interface for score submission state management.

    Provides idempotent retry handling through submission fingerprint tracking.
    """

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        """Create a new score submission record.

        Args:
            submission: ScoreSubmission domain object (id may be None)

        Returns:
            ScoreSubmission with assigned id

        Raises:
            IntegrityError: If fingerprint already exists
        """
        ...

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        """Retrieve submission by fingerprint for idempotent retry handling.

        Args:
            fingerprint: Unique submission fingerprint

        Returns:
            ScoreSubmission if found, None otherwise
        """
        ...

    async def update_state(
        self,
        submission_id: int,
        state: str,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        """Update submission processing state.

        Args:
            submission_id: Submission record ID
            state: New state ("received" | "processing" | "completed" |
                "terminal_rejected" | "retryable")
            result_snapshot: Optional client-safe result snapshot for idempotent retries

        Raises:
            ValueError: If submission_id not found
        """
        ...

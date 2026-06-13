"""SQLAlchemyScoreSubmissionRepository — async database-backed submission repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: TC002

from osu_server.domain.scores.submission import ScoreSubmission
from osu_server.repositories.sqlalchemy.models.score import ScoreSubmissionModel


class SQLAlchemyScoreSubmissionRepository:
    """SQLAlchemy implementation of the ScoreSubmissionRepository Protocol.

    Uses ``async_sessionmaker`` for database access. Each method opens
    its own session to keep transactions short.
    """

    _session_factory: async_sessionmaker[AsyncSession]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        """Persist a new submission and return it with a generated id.

        Raises ``ValueError`` if ``fingerprint`` already exists.
        """
        async with self._session_factory() as session:
            model = ScoreSubmissionModel(
                fingerprint=submission.fingerprint,
                user_id=submission.user_id,
                beatmap_checksum=submission.beatmap_checksum,
                submitted_at=submission.submitted_at,
                state=submission.state,
                result_snapshot=submission.result_snapshot,
            )
            session.add(model)
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                if "fingerprint" in str(e):
                    msg = f"fingerprint already exists: {submission.fingerprint}"
                    raise ValueError(msg) from e
                raise
            await session.refresh(model)

            return self._to_domain(model)

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        """Return submission with *fingerprint*, or ``None`` if not found."""
        async with self._session_factory() as session:
            stmt = select(ScoreSubmissionModel).where(
                ScoreSubmissionModel.fingerprint == fingerprint
            )
            result = (await session.execute(stmt)).scalar_one_or_none()
            return self._to_domain(result) if result is not None else None

    async def update_state(
        self,
        submission_id: int,
        state: str,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        """Update submission state.

        Raises ``ValueError`` if *submission_id* not found.
        """
        async with self._session_factory() as session:
            model = await session.get(ScoreSubmissionModel, submission_id)
            if model is None:
                msg = f"Submission not found: {submission_id}"
                raise ValueError(msg)

            model.state = state
            model.result_snapshot = result_snapshot
            await session.commit()

    @staticmethod
    def _to_domain(model: ScoreSubmissionModel) -> ScoreSubmission:
        """Map a SQLAlchemy ScoreSubmissionModel to a domain ScoreSubmission."""
        return ScoreSubmission(
            id=model.id,
            fingerprint=model.fingerprint,
            user_id=model.user_id,
            beatmap_checksum=model.beatmap_checksum,
            submitted_at=model.submitted_at,
            state=model.state,
            result_snapshot=model.result_snapshot,
        )

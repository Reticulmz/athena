"""SQLAlchemy command-side score submission repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.scores.submission import ScoreSubmission, ScoreSubmissionState
from osu_server.repositories.sqlalchemy.models.score import ScoreSubmissionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyScoreSubmissionCommandRepository:
    """Submission command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def create(self, submission: ScoreSubmission) -> ScoreSubmission:
        model = ScoreSubmissionModel(
            fingerprint=submission.fingerprint,
            user_id=submission.user_id,
            beatmap_checksum=submission.beatmap_checksum,
            submitted_at=submission.submitted_at,
            state=submission.state.value,
            result_snapshot=submission.result_snapshot,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "fingerprint" in str(exc):
                msg = f"fingerprint already exists: {submission.fingerprint}"
                raise ValueError(msg) from exc
            raise
        await self._session.refresh(model)
        return _submission_to_domain(model)

    async def get_by_fingerprint(self, fingerprint: str) -> ScoreSubmission | None:
        model = (
            await self._session.execute(
                select(ScoreSubmissionModel).where(ScoreSubmissionModel.fingerprint == fingerprint)
            )
        ).scalar_one_or_none()
        return _submission_to_domain(model) if isinstance(model, ScoreSubmissionModel) else None

    async def update_state(
        self,
        submission_id: int,
        state: ScoreSubmissionState,
        result_snapshot: dict[str, object] | None = None,
    ) -> None:
        model = await self._session.get(ScoreSubmissionModel, submission_id)
        if model is None:
            msg = f"Submission not found: {submission_id}"
            raise ValueError(msg)
        assert isinstance(model, ScoreSubmissionModel)

        model.state = state.value
        model.result_snapshot = result_snapshot
        await self._session.flush()


def _submission_to_domain(model: ScoreSubmissionModel) -> ScoreSubmission:
    return ScoreSubmission(
        id=model.id,
        fingerprint=model.fingerprint,
        user_id=model.user_id,
        beatmap_checksum=model.beatmap_checksum,
        submitted_at=model.submitted_at,
        state=ScoreSubmissionState(model.state),
        result_snapshot=model.result_snapshot,
    )

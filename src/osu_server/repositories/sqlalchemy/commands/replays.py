"""SQLAlchemy command-side replay repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.scores.replay import Replay
from osu_server.repositories.sqlalchemy.models.score import ReplayModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyReplayCommandRepository:
    """Replay command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def create(self, replay: Replay) -> Replay:
        model = ReplayModel(
            score_id=replay.score_id,
            blob_id=replay.blob_id,
            checksum_sha256=replay.checksum_sha256,
            byte_size=replay.byte_size,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "checksum_sha256" in str(exc):
                msg = f"checksum_sha256 already exists: {replay.checksum_sha256}"
                raise ValueError(msg) from exc
            raise
        await self._session.refresh(model)
        return _replay_to_domain(model)

    async def exists_by_checksum(self, checksum: str) -> bool:
        result = (
            await self._session.execute(
                select(ReplayModel.id).where(ReplayModel.checksum_sha256 == checksum)
            )
        ).scalar_one_or_none()
        return result is not None


def _replay_to_domain(model: ReplayModel) -> Replay:
    return Replay(
        id=model.id,
        score_id=model.score_id,
        blob_id=model.blob_id,
        checksum_sha256=model.checksum_sha256,
        byte_size=model.byte_size,
    )

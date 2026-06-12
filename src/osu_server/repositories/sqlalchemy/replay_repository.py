"""SQLAlchemyReplayRepository — async database-backed replay repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: TC002

from osu_server.domain.score.replay import Replay
from osu_server.repositories.sqlalchemy.models.score import ReplayModel


class SQLAlchemyReplayRepository:
    """SQLAlchemy implementation of the ReplayRepository Protocol.

    Uses ``async_sessionmaker`` for database access. Each method opens
    its own session to keep transactions short.
    """

    _session_factory: async_sessionmaker[AsyncSession]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, replay: Replay) -> Replay:
        """Persist a new replay and return it with a generated id.

        Raises ``ValueError`` if ``checksum_sha256`` already exists.
        """
        async with self._session_factory() as session:
            model = ReplayModel(
                score_id=replay.score_id,
                blob_id=replay.blob_id,
                checksum_sha256=replay.checksum_sha256,
                byte_size=replay.byte_size,
            )
            session.add(model)
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                if "checksum_sha256" in str(e):
                    msg = f"checksum_sha256 already exists: {replay.checksum_sha256}"
                    raise ValueError(msg) from e
                raise
            await session.refresh(model)

            return self._to_domain(model)

    async def exists_by_checksum(self, checksum: str) -> bool:
        """Return ``True`` if a replay with *checksum* exists."""
        async with self._session_factory() as session:
            stmt = select(ReplayModel.id).where(ReplayModel.checksum_sha256 == checksum)
            result = (await session.execute(stmt)).scalar_one_or_none()
            return result is not None

    @staticmethod
    def _to_domain(model: ReplayModel) -> Replay:
        """Map a SQLAlchemy ReplayModel to a domain Replay."""
        return Replay(
            id=model.id,
            score_id=model.score_id,
            blob_id=model.blob_id,
            checksum_sha256=model.checksum_sha256,
            byte_size=model.byte_size,
        )

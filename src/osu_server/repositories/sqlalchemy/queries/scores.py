"""SQLAlchemy query-side score repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.score import ScoreModel
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    score_to_domain,
)

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score


class SQLAlchemyScoreQueryRepository:
    """Read-only score repository backed by short SQLAlchemy sessions."""

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory = session_factory

    async def get_by_id(self, score_id: int) -> Score | None:
        async with self._session_factory() as session:
            model = await session.get(ScoreModel, score_id)
            return score_to_domain(model) if isinstance(model, ScoreModel) else None

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(ScoreModel).where(ScoreModel.online_checksum == checksum)
                )
            ).scalar_one_or_none()
            return score_to_domain(model) if isinstance(model, ScoreModel) else None

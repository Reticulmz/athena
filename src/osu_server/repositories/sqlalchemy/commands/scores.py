"""SQLAlchemy command-side score repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.sqlalchemy.models.score import ScoreModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyScoreCommandRepository:
    """Score command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def create(self, score: Score) -> Score:
        model = ScoreModel(
            user_id=score.user_id,
            beatmap_id=score.beatmap_id,
            beatmap_checksum=score.beatmap_checksum,
            online_checksum=score.online_checksum,
            ruleset=score.ruleset.value,
            playstyle=score.playstyle.value,
            mods=score.mods.to_persistence_bitmask(),
            n300=score.n300,
            n100=score.n100,
            n50=score.n50,
            geki=score.geki,
            katu=score.katu,
            miss=score.miss,
            score=score.score,
            max_combo=score.max_combo,
            accuracy=score.accuracy,
            grade=score.grade.value,
            passed=score.passed,
            perfect=score.perfect,
            client_version=score.client_version,
            submitted_at=score.submitted_at,
            beatmap_status_at_submission=score.beatmap_status_at_submission,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "online_checksum" in str(exc):
                msg = f"online_checksum already exists: {score.online_checksum}"
                raise ValueError(msg) from exc
            raise
        await self._session.refresh(model)
        return _score_to_domain(model)

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        result = (
            await self._session.execute(
                select(ScoreModel.id).where(ScoreModel.online_checksum == checksum)
            )
        ).scalar_one_or_none()
        return result is not None

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        model = (
            await self._session.execute(
                select(ScoreModel).where(ScoreModel.online_checksum == checksum)
            )
        ).scalar_one_or_none()
        return _score_to_domain(model) if isinstance(model, ScoreModel) else None

    async def get_by_id(self, score_id: int) -> Score | None:
        model = await self._session.get(ScoreModel, score_id)
        return _score_to_domain(model) if isinstance(model, ScoreModel) else None


def _score_to_domain(model: ScoreModel) -> Score:
    return Score(
        id=model.id,
        user_id=model.user_id,
        beatmap_id=model.beatmap_id,
        beatmap_checksum=model.beatmap_checksum,
        online_checksum=model.online_checksum,
        ruleset=Ruleset(model.ruleset),
        playstyle=Playstyle(model.playstyle),
        mods=ModCombination.from_persistence_bitmask(model.mods),
        n300=model.n300,
        n100=model.n100,
        n50=model.n50,
        geki=model.geki,
        katu=model.katu,
        miss=model.miss,
        score=model.score,
        max_combo=model.max_combo,
        accuracy=model.accuracy,
        grade=Grade(model.grade),
        passed=model.passed,
        perfect=model.perfect,
        client_version=model.client_version,
        submitted_at=model.submitted_at,
        beatmap_status_at_submission=model.beatmap_status_at_submission,
    )

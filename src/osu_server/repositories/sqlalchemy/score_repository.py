"""SQLAlchemyScoreRepository — async database-backed score repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: TC002

from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.sqlalchemy.models.score import ScoreModel


class SQLAlchemyScoreRepository:
    """SQLAlchemy implementation of the ScoreRepository Protocol.

    Uses ``async_sessionmaker`` for database access. Each method opens
    its own session to keep transactions short.
    """

    _session_factory: async_sessionmaker[AsyncSession]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, score: Score) -> Score:
        """Persist a new score and return it with a generated id.

        Raises ``ValueError`` if ``online_checksum`` already exists.
        """
        async with self._session_factory() as session:
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
                leaderboard_eligible_at_submission=score.leaderboard_eligible_at_submission,
            )
            session.add(model)
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                if "online_checksum" in str(e):
                    msg = f"online_checksum already exists: {score.online_checksum}"
                    raise ValueError(msg) from e
                raise
            await session.refresh(model)

            return self._to_domain(model)

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        """Return ``True`` if a score with *checksum* exists."""
        async with self._session_factory() as session:
            stmt = select(ScoreModel.id).where(ScoreModel.online_checksum == checksum)
            result = (await session.execute(stmt)).scalar_one_or_none()
            return result is not None

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Return the score with *checksum*, or ``None`` if not found."""
        async with self._session_factory() as session:
            stmt = select(ScoreModel).where(ScoreModel.online_checksum == checksum)
            model = (await session.execute(stmt)).scalar_one_or_none()
            return self._to_domain(model) if model is not None else None

    async def get_by_id(self, score_id: int) -> Score | None:
        """Return the score with *score_id*, or ``None`` if not found."""
        async with self._session_factory() as session:
            model = await session.get(ScoreModel, score_id)
            return self._to_domain(model) if model is not None else None

    @staticmethod
    def _to_domain(model: ScoreModel) -> Score:
        """Map a SQLAlchemy ScoreModel to a domain Score."""
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
            leaderboard_eligible_at_submission=model.leaderboard_eligible_at_submission,
        )

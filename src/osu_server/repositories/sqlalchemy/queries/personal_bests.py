"""SQLAlchemy query-side personal best repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from osu_server.domain.compatibility.stable.getscores import GetscoresPersonalBest
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.sqlalchemy.models.personal_best import PersonalBestModel
from osu_server.repositories.sqlalchemy.models.score import ReplayModel, ScoreModel
from osu_server.repositories.sqlalchemy.models.user import UserModel

if TYPE_CHECKING:
    from sqlalchemy.sql.base import Executable

    from osu_server.domain.scores.personal_best import LeaderboardCategory
    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_ROW_TUPLE_LENGTH = 4


class SQLAlchemyPersonalBestQueryRepository:
    """Read-only personal best projection repository backed by short sessions."""

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory = session_factory

    async def get_personal_best(
        self,
        *,
        user_id: int,
        beatmap_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
        category: LeaderboardCategory,
    ) -> GetscoresPersonalBest | None:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    _personal_best_statement(
                        user_id=user_id,
                        beatmap_id=beatmap_id,
                        ruleset=ruleset,
                        playstyle=playstyle,
                        category=category,
                    )
                )
            ).all()

        for score_model, username, has_replay, rank in _iter_personal_best_rows(rows):
            return _score_listing_from_models(
                score_model=score_model,
                username=username,
                has_replay=has_replay,
                rank=rank,
            )

        return None


def _personal_best_statement(
    *,
    user_id: int,
    beatmap_id: int,
    ruleset: Ruleset,
    playstyle: Playstyle,
    category: LeaderboardCategory,
) -> Executable:
    better_personal_best = aliased(PersonalBestModel)
    replay_exists = (
        select(ReplayModel.id).where(ReplayModel.score_id == ScoreModel.id).limit(1).exists()
    )
    rank = (
        select(func.count(better_personal_best.id) + 1)
        .where(
            better_personal_best.beatmap_id == PersonalBestModel.beatmap_id,
            better_personal_best.ruleset == PersonalBestModel.ruleset,
            better_personal_best.playstyle == PersonalBestModel.playstyle,
            better_personal_best.category == PersonalBestModel.category,
            better_personal_best.ranking_value > PersonalBestModel.ranking_value,
        )
        .scalar_subquery()
    )
    return (
        select(
            ScoreModel,
            UserModel.username,
            replay_exists.label("has_replay"),
            rank.label("rank"),
        )
        .join(PersonalBestModel, PersonalBestModel.score_id == ScoreModel.id)
        .join(UserModel, UserModel.id == ScoreModel.user_id)
        .where(
            PersonalBestModel.user_id == user_id,
            PersonalBestModel.beatmap_id == beatmap_id,
            PersonalBestModel.ruleset == ruleset.value,
            PersonalBestModel.playstyle == playstyle.value,
            PersonalBestModel.category == category.value,
        )
        .limit(1)
    )


def _iter_personal_best_rows(
    rows: object,
) -> list[tuple[ScoreModel, str, bool, int]]:
    result: list[tuple[ScoreModel, str, bool, int]] = []
    for row in cast("list[object]", rows):
        if isinstance(row, tuple):
            values = cast("tuple[object, ...]", row)
            if (
                len(values) == _ROW_TUPLE_LENGTH
                and isinstance(values[0], ScoreModel)
                and isinstance(values[1], str)
                and isinstance(values[3], int)
            ):
                result.append((values[0], values[1], bool(values[2]), values[3]))
            continue

        score_model = getattr(row, "ScoreModel", None)
        username = getattr(row, "username", None)
        has_replay = getattr(row, "has_replay", None)
        rank = getattr(row, "rank", None)
        if (
            isinstance(score_model, ScoreModel)
            and isinstance(username, str)
            and isinstance(rank, int)
        ):
            result.append((score_model, username, bool(has_replay), rank))

    return result


def _score_listing_from_models(
    *,
    score_model: ScoreModel,
    username: str,
    has_replay: bool,
    rank: int,
) -> GetscoresPersonalBest:
    return GetscoresPersonalBest(
        score_id=score_model.id,
        user_id=score_model.user_id,
        username=username,
        beatmap_id=score_model.beatmap_id,
        ruleset=Ruleset(score_model.ruleset),
        playstyle=Playstyle(score_model.playstyle),
        score=score_model.score,
        max_combo=score_model.max_combo,
        n50=score_model.n50,
        n100=score_model.n100,
        n300=score_model.n300,
        miss=score_model.miss,
        katu=score_model.katu,
        geki=score_model.geki,
        perfect=score_model.perfect,
        mods=score_model.mods,
        rank=rank,
        submitted_at=score_model.submitted_at,
        has_replay=has_replay,
    )

"""SQLAlchemy command-side personal best repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert

from osu_server.domain.scores.personal_best import (
    LeaderboardCategory,
    PersonalBest,
    PersonalBestScope,
)
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.sqlalchemy.models.personal_best import PersonalBestModel

if TYPE_CHECKING:
    from sqlalchemy.dialects.postgresql.dml import Insert
    from sqlalchemy.ext.asyncio import AsyncSession

    from osu_server.repositories.interfaces.commands.personal_bests import UpsertPersonalBest


class SQLAlchemyPersonalBestCommandRepository:
    """Personal best command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def get_by_scope(self, scope: PersonalBestScope) -> PersonalBest | None:
        model = (
            await self._session.execute(
                _select_by_scope(scope),
            )
        ).scalar_one_or_none()
        return _model_to_domain(model) if isinstance(model, PersonalBestModel) else None

    async def upsert_if_better(self, command: UpsertPersonalBest) -> PersonalBest:
        _ = await self._session.execute(_upsert_if_better_statement(command))
        model = (
            await self._session.execute(
                _select_by_scope(command.scope).with_for_update(),
            )
        ).scalar_one_or_none()

        if isinstance(model, PersonalBestModel):
            return _model_to_domain(model)
        msg = "personal best upsert did not return a persisted projection"
        raise RuntimeError(msg)


def _select_by_scope(scope: PersonalBestScope) -> Select[tuple[PersonalBestModel]]:
    return select(PersonalBestModel).where(
        PersonalBestModel.user_id == scope.user_id,
        PersonalBestModel.beatmap_id == scope.beatmap_id,
        PersonalBestModel.ruleset == scope.ruleset.value,
        PersonalBestModel.playstyle == scope.playstyle.value,
        PersonalBestModel.category == scope.category.value,
    )


def _upsert_if_better_statement(command: UpsertPersonalBest) -> Insert:
    insert_statement = insert(PersonalBestModel).values(
        user_id=command.scope.user_id,
        beatmap_id=command.scope.beatmap_id,
        ruleset=command.scope.ruleset.value,
        playstyle=command.scope.playstyle.value,
        category=command.scope.category.value,
        score_id=command.score_id,
        ranking_value=command.ranking_value,
    )
    return insert_statement.on_conflict_do_update(
        index_elements=[
            PersonalBestModel.user_id,
            PersonalBestModel.beatmap_id,
            PersonalBestModel.ruleset,
            PersonalBestModel.playstyle,
            PersonalBestModel.category,
        ],
        set_={
            "score_id": command.score_id,
            "ranking_value": command.ranking_value,
        },
        where=PersonalBestModel.ranking_value < command.ranking_value,
    )


def _model_to_domain(model: PersonalBestModel) -> PersonalBest:
    return PersonalBest(
        id=model.id,
        scope=PersonalBestScope(
            user_id=model.user_id,
            beatmap_id=model.beatmap_id,
            ruleset=Ruleset(model.ruleset),
            playstyle=Playstyle(model.playstyle),
            category=LeaderboardCategory(model.category),
        ),
        score_id=model.score_id,
        ranking_value=model.ranking_value,
    )

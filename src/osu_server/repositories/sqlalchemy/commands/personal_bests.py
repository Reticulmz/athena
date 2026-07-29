"""SQLAlchemyでscore personal best projectionを永続化するrepositoryを提供する."""

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
    """Unit of Work所有sessionでpersonal best projectionを更新するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): personal best操作に使うsession.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def get_by_scope(self, scope: PersonalBestScope) -> PersonalBest | None:
        """完全なpersonal best scopeに対応するprojectionを取得する.

        Args:
            scope (PersonalBestScope): userとbeatmapとrulesetとplaystyleとcategoryから成る取得条件.

        Returns:
            PersonalBest | None: 対応するpersonal best. 未作成の場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.

        Notes:
            userとbeatmapとrulesetとplaystyleとcategoryを完全一致で照合する.
        """
        model = (
            await self._session.execute(
                _select_by_scope(scope),
            )
        ).scalar_one_or_none()
        return _model_to_domain(model) if isinstance(model, PersonalBestModel) else None

    async def upsert_if_better(self, command: UpsertPersonalBest) -> PersonalBest:
        """Ranking valueがより良い場合だけpersonal best projectionを更新する.

        Args:
            command (UpsertPersonalBest): scopeとcandidate scoreとranking valueを持つ更新command.

        Returns:
            PersonalBest: 更新後または既存の永続化済みpersonal best.

        Raises:
            RuntimeError: upsert後に対応するprojectionを再取得できない場合.
            SQLAlchemyError: upsertまたはrow lock付きselectに失敗した場合.

        Notes:
            ranking valueが既存値以下ならdatabase conflict条件により既存値を保持する.
        """
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
    """Personal best scopeに一致するprojectionを取得するselectを作る.

    Args:
        scope (PersonalBestScope): userとbeatmapとrulesetとplaystyleとcategoryの完全一致条件.

    Returns:
        Select[tuple[PersonalBestModel]]: 対応するpersonal best rowを返すSQLAlchemy select.
    """
    return select(PersonalBestModel).where(
        PersonalBestModel.user_id == scope.user_id,
        PersonalBestModel.beatmap_id == scope.beatmap_id,
        PersonalBestModel.ruleset == scope.ruleset.value,
        PersonalBestModel.playstyle == scope.playstyle.value,
        PersonalBestModel.category == scope.category.value,
    )


def _upsert_if_better_statement(command: UpsertPersonalBest) -> Insert:
    """より良いranking valueだけを反映するPostgreSQL upsertを作る.

    Args:
        command (UpsertPersonalBest): insert値と更新判定に使うcandidate personal best.

    Returns:
        Insert: scopeをconflict keyにしてranking valueを比較するPostgreSQL insert statement.

    Notes:
        同値または低いranking valueは保存済みrowを変更しない.
    """
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
    """SQLAlchemy personal best modelをdomain projectionへ変換する.

    Args:
        model (PersonalBestModel): 永続化層から読み出したpersonal best row.

    Returns:
        PersonalBest: scopeの有限値をdomain enumへ復元したpersonal best.

    Raises:
        ValueError: 保存されたrulesetかplaystyleかcategoryが既知のenum値でない場合.
    """
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

"""SQLAlchemyでcurrent UserStats projectionを永続化するrepositoryを提供する."""

from __future__ import annotations

from hashlib import blake2b
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import (
    UserStatsHitTotals,
    UserStatsProjection,
    UserStatsScope,
)
from osu_server.repositories.sqlalchemy.models.user_stats import CurrentUserStatsModel

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.dialects.postgresql.dml import Insert
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyCurrentUserStatsCommandRepository:
    """Unit of Work所有sessionでcurrent UserStats projectionを更新するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): UserStats projection操作に使うsession.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def lock_scope(self, scope: UserStatsScope) -> None:
        """同一UserStats scopeのprojection refreshをtransaction内で直列化する.

        Args:
            scope (UserStatsScope): userとrulesetとplaystyleから成る排他対象scope.

        Returns:
            None: transaction advisory lockを取得したことを示す.

        Raises:
            SQLAlchemyError: PostgreSQL advisory lockの実行に失敗した場合.

        Notes:
            lockはtransaction終了時に解放されるためこのmethodはcommitしない.
        """
        _ = await self._session.execute(select(func.pg_advisory_xact_lock(_scope_lock_key(scope))))

    async def get(self, scope: UserStatsScope) -> UserStatsProjection | None:
        """指定scopeのcurrent UserStats projectionを取得する.

        Args:
            scope (UserStatsScope): userとrulesetとplaystyleから成る取得対象scope.

        Returns:
            UserStatsProjection | None: 対応するprojection. 未作成の場合はNone.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        model = (await self._session.execute(_select_by_scope(scope))).scalar_one_or_none()
        return _model_to_domain(model) if isinstance(model, CurrentUserStatsModel) else None

    async def replace(self, projection: UserStatsProjection) -> UserStatsProjection:
        """指定scopeのcurrent UserStats projectionをupsertで置き換える.

        Args:
            projection (UserStatsProjection): scopeと集計済みstatisticsを持つ新しいprojection.

        Returns:
            UserStatsProjection: row lock下で再取得した永続化済みprojection.

        Raises:
            RuntimeError: upsert後に対応するprojectionを再取得できない場合.
            SQLAlchemyError: upsertまたはrow lock付きselectに失敗した場合.

        Notes:
            callerは事前にlock_scopeで同じscopeを直列化できる. このmethodはcommitしない.
        """
        _ = await self._session.execute(_replace_statement(projection))
        model = (
            await self._session.execute(_select_by_scope(projection.scope).with_for_update())
        ).scalar_one_or_none()
        if isinstance(model, CurrentUserStatsModel):
            return _model_to_domain(model)
        msg = "current user stats replace did not return a persisted projection"
        raise RuntimeError(msg)


def _select_by_scope(scope: UserStatsScope) -> Select[tuple[CurrentUserStatsModel]]:
    """UserStats scopeに一致するprojectionを取得するselectを作る.

    Args:
        scope (UserStatsScope): userとrulesetとplaystyleから成る完全一致条件.

    Returns:
        Select[tuple[CurrentUserStatsModel]]: 対応するprojection rowを返すSQLAlchemy select.
    """
    return select(CurrentUserStatsModel).where(
        CurrentUserStatsModel.user_id == scope.user_id,
        CurrentUserStatsModel.ruleset == scope.ruleset.value,
        CurrentUserStatsModel.playstyle == scope.playstyle.value,
    )


def _scope_lock_key(scope: UserStatsScope) -> int:
    """UserStats scopeをPostgreSQL advisory lock用のsigned 64-bit keyへ変換する.

    Args:
        scope (UserStatsScope): hash化するuserとrulesetとplaystyleの組.

    Returns:
        int: PostgreSQL advisory lockへ渡せるsigned 64-bit整数.

    Notes:
        Blake2b digestのunsigned値をtwo's complement表現へ正規化する.
    """
    payload = (
        f"current_user_stats:{scope.user_id}:{scope.ruleset.value}:{scope.playstyle.value}"
    ).encode()
    value = int.from_bytes(blake2b(payload, digest_size=8).digest(), byteorder="big")
    if value >= 2**63:
        return value - 2**64
    return value


def _replace_statement(projection: UserStatsProjection) -> Insert:
    """Current UserStats projectionを置換するPostgreSQL upsertを作る.

    Args:
        projection (UserStatsProjection): insert値とconflict更新値のsource.

    Returns:
        Insert: user/ruleset/playstyleをconflict keyにするPostgreSQL insert statement.

    Notes:
        conflict時はscope以外のstatisticsとupdated_atだけを更新する.
    """
    values = _projection_values(projection)
    return (
        insert(CurrentUserStatsModel)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["user_id", "ruleset", "playstyle"],
            set_={
                key: value
                for key, value in values.items()
                if key not in {"user_id", "ruleset", "playstyle"}
            }
            | {"updated_at": func.now()},
        )
    )


def _projection_values(projection: UserStatsProjection) -> dict[str, object]:
    """Domain projectionをSQLAlchemy upsert用のcolumn value mappingへ変換する.

    Args:
        projection (UserStatsProjection): 永続化するscopeとstatistics.

    Returns:
        dict[str, object]: CurrentUserStatsModelのcolumn名をkeyにする値mapping.
    """
    hit_totals = projection.hit_totals
    return {
        "user_id": projection.scope.user_id,
        "ruleset": projection.scope.ruleset.value,
        "playstyle": projection.scope.playstyle.value,
        "pp": projection.pp,
        "accuracy": projection.accuracy,
        "play_count": projection.play_count,
        "ranked_score": projection.ranked_score,
        "total_score": projection.total_score,
        "max_combo": projection.max_combo,
        "play_time_seconds": projection.play_time_seconds,
        "count_300": hit_totals.count_300,
        "count_100": hit_totals.count_100,
        "count_50": hit_totals.count_50,
        "count_geki": hit_totals.count_geki,
        "count_katu": hit_totals.count_katu,
        "count_miss": hit_totals.count_miss,
    }


def _model_to_domain(model: CurrentUserStatsModel) -> UserStatsProjection:
    """SQLAlchemy UserStats projection modelをdomain projectionへ変換する.

    Args:
        model (CurrentUserStatsModel): 永続化層から読み出したprojection row.

    Returns:
        UserStatsProjection: rulesetとplaystyleをdomain enumへ復元したprojection.

    Raises:
        ValueError: 保存されたrulesetまたはplaystyleが既知のenum値でない場合.
    """
    return UserStatsProjection(
        scope=UserStatsScope(
            user_id=model.user_id,
            ruleset=Ruleset(model.ruleset),
            playstyle=Playstyle(model.playstyle),
        ),
        pp=model.pp,
        accuracy=model.accuracy,
        play_count=model.play_count,
        ranked_score=model.ranked_score,
        total_score=model.total_score,
        max_combo=model.max_combo,
        play_time_seconds=model.play_time_seconds,
        hit_totals=UserStatsHitTotals(
            count_300=model.count_300,
            count_100=model.count_100,
            count_50=model.count_50,
            count_geki=model.count_geki,
            count_katu=model.count_katu,
            count_miss=model.count_miss,
        ),
    )


__all__ = ("SQLAlchemyCurrentUserStatsCommandRepository",)

"""SQLAlchemy command-side current UserStats projection repository."""

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
    """UoW-owned SQLAlchemy session を使う current UserStats command repository。"""

    def __init__(self, session: AsyncSession) -> None:
        """SQLAlchemy session を UoW から受け取る。"""
        self._session: AsyncSession = session

    async def lock_scope(self, scope: UserStatsScope) -> None:
        """同一 user/mode の projection refresh を transaction 内で直列化する。"""
        _ = await self._session.execute(select(func.pg_advisory_xact_lock(_scope_lock_key(scope))))

    async def get(self, scope: UserStatsScope) -> UserStatsProjection | None:
        """指定 scope の current UserStats projection row を返す。"""
        model = (await self._session.execute(_select_by_scope(scope))).scalar_one_or_none()
        return _model_to_domain(model) if isinstance(model, CurrentUserStatsModel) else None

    async def replace(self, projection: UserStatsProjection) -> UserStatsProjection:
        """指定 scope の current UserStats projection row を upsert で置き換える。"""
        _ = await self._session.execute(_replace_statement(projection))
        model = (
            await self._session.execute(_select_by_scope(projection.scope).with_for_update())
        ).scalar_one_or_none()
        if isinstance(model, CurrentUserStatsModel):
            return _model_to_domain(model)
        msg = "current user stats replace did not return a persisted projection"
        raise RuntimeError(msg)


def _select_by_scope(scope: UserStatsScope) -> Select[tuple[CurrentUserStatsModel]]:
    return select(CurrentUserStatsModel).where(
        CurrentUserStatsModel.user_id == scope.user_id,
        CurrentUserStatsModel.ruleset == scope.ruleset.value,
        CurrentUserStatsModel.playstyle == scope.playstyle.value,
    )


def _scope_lock_key(scope: UserStatsScope) -> int:
    payload = (
        f"current_user_stats:{scope.user_id}:{scope.ruleset.value}:{scope.playstyle.value}"
    ).encode()
    value = int.from_bytes(blake2b(payload, digest_size=8).digest(), byteorder="big")
    if value >= 2**63:
        return value - 2**64
    return value


def _replace_statement(projection: UserStatsProjection) -> Insert:
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

"""SQLAlchemy command-side beatmap performance best projection repository."""

from __future__ import annotations

from hashlib import blake2b
from typing import TYPE_CHECKING

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBest,
    BeatmapPerformanceBestScope,
    BeatmapPerformanceBestUserProjectionSlice,
)
from osu_server.repositories.sqlalchemy.models.user_stats import (
    BeatmapPerformanceBestModel,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.dialects.postgresql.dml import Insert
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.dml import Delete
    from sqlalchemy.sql.elements import ColumnElement

    from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
        BeatmapPerformanceBestProjectionSlice,
        UpsertBeatmapPerformanceBest,
    )


class SQLAlchemyBeatmapPerformanceBestCommandRepository:
    """UoW-owned SQLAlchemy session を使う performance best command repository。"""

    def __init__(self, session: AsyncSession) -> None:
        """SQLAlchemy session を UoW から受け取る。"""
        self._session: AsyncSession = session

    async def lock_scope(self, scope: BeatmapPerformanceBestScope) -> None:
        """同一 performance best scope の refresh を transaction 内で直列化する。"""
        _ = await self._session.execute(select(func.pg_advisory_xact_lock(_scope_lock_key(scope))))

    async def get_best(
        self,
        scope: BeatmapPerformanceBestScope,
    ) -> BeatmapPerformanceBest | None:
        """指定 scope の現在の performance best row を返す。"""
        model = (await self._session.execute(_select_by_scope(scope))).scalar_one_or_none()
        return _model_to_domain(model) if isinstance(model, BeatmapPerformanceBestModel) else None

    async def upsert_if_better(
        self,
        command: UpsertBeatmapPerformanceBest,
    ) -> BeatmapPerformanceBest:
        """候補が PP 優先順で上位なら upsert し、現在 row を返す。"""
        _ = await self._session.execute(_upsert_if_better_statement(command))
        model = (
            await self._session.execute(_select_by_scope(command.scope).with_for_update())
        ).scalar_one_or_none()

        if isinstance(model, BeatmapPerformanceBestModel):
            return _model_to_domain(model)
        msg = "beatmap performance best upsert did not return a persisted projection"
        raise RuntimeError(msg)

    async def replace_projection_slice(
        self,
        slice_: BeatmapPerformanceBestProjectionSlice,
        rows: Iterable[UpsertBeatmapPerformanceBest],
    ) -> None:
        """指定 slice 内の stale rows を削除し、supplied rows を投入する。"""
        rows_to_insert = tuple(rows)
        for row in rows_to_insert:
            if not _slice_contains(slice_, row.scope):
                msg = "replacement row is outside projection slice"
                raise ValueError(msg)

        _ = await self._session.execute(_delete_slice_statement(slice_))
        for row in rows_to_insert:
            _ = await self.upsert_if_better(row)

    async def replace_scope(
        self,
        scope: BeatmapPerformanceBestScope,
        row: UpsertBeatmapPerformanceBest | None,
    ) -> BeatmapPerformanceBest | None:
        """1 scope の stale row を削除し、supplied winner があれば投入する。"""
        if row is not None and row.scope != scope:
            msg = "replacement row is outside projection scope"
            raise ValueError(msg)

        _ = await self._session.execute(_delete_scope_statement(scope))
        if row is None:
            return None
        return await self.upsert_if_better(row)

    async def list_user_bests(
        self,
        *,
        user_id: int,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[BeatmapPerformanceBest, ...]:
        """指定 user/mode の current performance best rows を返す。"""
        models = (
            await self._session.execute(
                select(BeatmapPerformanceBestModel)
                .where(
                    BeatmapPerformanceBestModel.user_id == user_id,
                    BeatmapPerformanceBestModel.ruleset == ruleset.value,
                    BeatmapPerformanceBestModel.playstyle == playstyle.value,
                )
                .order_by(
                    BeatmapPerformanceBestModel.pp.desc(),
                    BeatmapPerformanceBestModel.submitted_at.asc(),
                    BeatmapPerformanceBestModel.score_id.asc(),
                )
            )
        ).scalars()
        return tuple(_model_to_domain(model) for model in models)


def _select_by_scope(
    scope: BeatmapPerformanceBestScope,
) -> Select[tuple[BeatmapPerformanceBestModel]]:
    return select(BeatmapPerformanceBestModel).where(*_scope_conditions(scope))


def _scope_conditions(
    scope: BeatmapPerformanceBestScope,
) -> tuple[ColumnElement[bool], ...]:
    return (
        BeatmapPerformanceBestModel.user_id == scope.user_id,
        BeatmapPerformanceBestModel.beatmap_id == scope.beatmap_id,
        BeatmapPerformanceBestModel.ruleset == scope.ruleset.value,
        BeatmapPerformanceBestModel.playstyle == scope.playstyle.value,
    )


def _scope_lock_key(scope: BeatmapPerformanceBestScope) -> int:
    payload = (
        "beatmap_performance_bests:"
        f"{scope.user_id}:{scope.beatmap_id}:{scope.ruleset.value}:{scope.playstyle.value}"
    ).encode()
    value = int.from_bytes(blake2b(payload, digest_size=8).digest(), byteorder="big")
    if value >= 2**63:
        return value - 2**64
    return value


def _upsert_if_better_statement(command: UpsertBeatmapPerformanceBest) -> Insert:
    insert_statement = insert(BeatmapPerformanceBestModel).values(
        user_id=command.scope.user_id,
        beatmap_id=command.scope.beatmap_id,
        ruleset=command.scope.ruleset.value,
        playstyle=command.scope.playstyle.value,
        score_id=command.score_id,
        performance_calculation_id=command.performance_calculation_id,
        pp=command.pp,
        accuracy=command.accuracy,
        score=command.score,
        submitted_at=command.submitted_at,
    )
    return insert_statement.on_conflict_do_update(
        index_elements=[
            BeatmapPerformanceBestModel.user_id,
            BeatmapPerformanceBestModel.beatmap_id,
            BeatmapPerformanceBestModel.ruleset,
            BeatmapPerformanceBestModel.playstyle,
        ],
        set_={
            "score_id": command.score_id,
            "performance_calculation_id": command.performance_calculation_id,
            "pp": command.pp,
            "accuracy": command.accuracy,
            "score": command.score,
            "submitted_at": command.submitted_at,
            "updated_at": func.now(),
        },
        where=_candidate_beats_current(command),
    )


def _candidate_beats_current(command: UpsertBeatmapPerformanceBest) -> ColumnElement[bool]:
    return or_(
        BeatmapPerformanceBestModel.pp < command.pp,
        and_(
            BeatmapPerformanceBestModel.pp == command.pp,
            BeatmapPerformanceBestModel.submitted_at > command.submitted_at,
        ),
        and_(
            BeatmapPerformanceBestModel.pp == command.pp,
            BeatmapPerformanceBestModel.submitted_at == command.submitted_at,
            BeatmapPerformanceBestModel.score_id > command.score_id,
        ),
    )


def _delete_slice_statement(slice_: BeatmapPerformanceBestProjectionSlice) -> Delete:
    statement = delete(BeatmapPerformanceBestModel)
    if isinstance(slice_, BeatmapPerformanceBestUserProjectionSlice):
        return statement.where(BeatmapPerformanceBestModel.user_id == slice_.user_id)
    return statement.where(BeatmapPerformanceBestModel.beatmap_id.in_(slice_.beatmap_ids))


def _delete_scope_statement(scope: BeatmapPerformanceBestScope) -> Delete:
    return delete(BeatmapPerformanceBestModel).where(*_scope_conditions(scope))


def _slice_contains(
    slice_: BeatmapPerformanceBestProjectionSlice,
    scope: BeatmapPerformanceBestScope,
) -> bool:
    if isinstance(slice_, BeatmapPerformanceBestUserProjectionSlice):
        return scope.user_id == slice_.user_id
    return scope.beatmap_id in slice_.beatmap_ids


def _model_to_domain(model: BeatmapPerformanceBestModel) -> BeatmapPerformanceBest:
    return BeatmapPerformanceBest(
        id=model.id,
        scope=BeatmapPerformanceBestScope(
            user_id=model.user_id,
            beatmap_id=model.beatmap_id,
            ruleset=Ruleset(model.ruleset),
            playstyle=Playstyle(model.playstyle),
        ),
        score_id=model.score_id,
        performance_calculation_id=model.performance_calculation_id,
        pp=model.pp,
        accuracy=model.accuracy,
        score=model.score,
        submitted_at=model.submitted_at,
    )

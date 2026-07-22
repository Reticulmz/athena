"""SQLAlchemy を用いて beatmap performance best projection を永続化する command repository."""

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
    """UoW 所有の SQLAlchemy session で performance best projection を永続化する repository.

    Attributes:
        _session (AsyncSession): 呼び出し元の Unit of Work が所有する非同期 session.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Work 所有の SQLAlchemy session を保存する.

        Args:
            session (AsyncSession): command transaction を共有する非同期 session.

        Returns:
            None: repository の初期化だけを行い transaction を開始または確定しないことを示す.
        """
        self._session: AsyncSession = session

    async def lock_scope(self, scope: BeatmapPerformanceBestScope) -> None:
        """同一 performance best scope の refresh を transaction 内で直列化する.

        Args:
            scope (BeatmapPerformanceBestScope): user、beatmap、ruleset、playstyle を含む
                lock scope.

        Returns:
            None: 対応する PostgreSQL advisory transaction lock を取得したことを示す.
        """
        _ = await self._session.execute(select(func.pg_advisory_xact_lock(_scope_lock_key(scope))))

    async def get_best(
        self,
        scope: BeatmapPerformanceBestScope,
    ) -> BeatmapPerformanceBest | None:
        """指定 scope の現在の performance best row を返す.

        Args:
            scope (BeatmapPerformanceBestScope): raw Mod を持たない performance best の
                natural key.

        Returns:
            BeatmapPerformanceBest | None: 保存済みの best row. 未登録時は None.
        """
        model = (await self._session.execute(_select_by_scope(scope))).scalar_one_or_none()
        return _model_to_domain(model) if isinstance(model, BeatmapPerformanceBestModel) else None

    async def upsert_if_better(
        self,
        command: UpsertBeatmapPerformanceBest,
    ) -> BeatmapPerformanceBest:
        """候補が PP 優先順で上位なら upsert し現在 row を返す.

        Args:
            command (UpsertBeatmapPerformanceBest): 比較対象の scope、score、performance 候補.

        Returns:
            BeatmapPerformanceBest: upsert 後に scope を所有する保存 row.

        Raises:
            RuntimeError: upsert 後に保存 row を取得できない場合.
        """
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
        """指定 slice 内の stale row を削除し supplied row を投入する.

        Args:
            slice_ (BeatmapPerformanceBestProjectionSlice): user または beatmap ID 群による
                置換範囲.
            rows (Iterable[UpsertBeatmapPerformanceBest]): 置換後に保持する performance best 候補.

        Returns:
            None: slice の削除と候補の upsert が完了したことを示す.

        Raises:
            ValueError: rows に slice 外の scope が含まれる場合.
        """
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
        """1 scope の stale row を削除し supplied winner があれば投入する.

        Args:
            scope (BeatmapPerformanceBestScope): 削除または置換する完全一致 scope.
            row (UpsertBeatmapPerformanceBest | None): 新しい winner. None の場合は削除だけを行う.

        Returns:
            BeatmapPerformanceBest | None: 保存した winner. row が None の場合は None.

        Raises:
            ValueError: row の scope が指定 scope と一致しない場合.
        """
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
        """指定 user と mode の current performance best row を優先順で返す.

        Args:
            user_id (int): 検索する user ID.
            ruleset (Ruleset): 対象 ruleset.
            playstyle (Playstyle): 対象 playstyle.

        Returns:
            tuple[BeatmapPerformanceBest, ...]: PP 降順、送信時刻昇順、score ID 昇順の best row.
        """
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
    """Performance best の完全一致 scope を検索する SELECT statement を構築する.

    Args:
        scope (BeatmapPerformanceBestScope): user、beatmap、ruleset、playstyle の natural key.

    Returns:
        Select[tuple[BeatmapPerformanceBestModel]]: scope に一致する保存 row だけを返す statement.
    """
    return select(BeatmapPerformanceBestModel).where(*_scope_conditions(scope))


def _scope_conditions(
    scope: BeatmapPerformanceBestScope,
) -> tuple[ColumnElement[bool], ...]:
    """Performance best の natural key を比較する SQLAlchemy 条件を返す.

    Args:
        scope (BeatmapPerformanceBestScope): 比較する user、beatmap、ruleset、playstyle の scope.

    Returns:
        tuple[ColumnElement[bool], ...]: scope の各永続化列を完全一致で比較する条件.
    """
    return (
        BeatmapPerformanceBestModel.user_id == scope.user_id,
        BeatmapPerformanceBestModel.beatmap_id == scope.beatmap_id,
        BeatmapPerformanceBestModel.ruleset == scope.ruleset.value,
        BeatmapPerformanceBestModel.playstyle == scope.playstyle.value,
    )


def _scope_lock_key(scope: BeatmapPerformanceBestScope) -> int:
    """Performance best scope を PostgreSQL advisory lock 用の signed 64-bit key に変換する.

    Args:
        scope (BeatmapPerformanceBestScope): user、beatmap、ruleset、playstyle を含む lock scope.

    Returns:
        int: 同じ scope から常に得られる PostgreSQL bigint 範囲の lock key.

    Notes:
        Mod は performance best の serialization identity に含めない.
    """
    payload = (
        "beatmap_performance_bests:"
        f"{scope.user_id}:{scope.beatmap_id}:{scope.ruleset.value}:{scope.playstyle.value}"
    ).encode()
    value = int.from_bytes(blake2b(payload, digest_size=8).digest(), byteorder="big")
    if value >= 2**63:
        return value - 2**64
    return value


def _upsert_if_better_statement(command: UpsertBeatmapPerformanceBest) -> Insert:
    """候補が既存 row より優先される場合だけ更新する UPSERT statement を構築する.

    Args:
        command (UpsertBeatmapPerformanceBest): 保存する scope、score、performance 計算結果の候補.

    Returns:
        Insert: natural key 競合時に候補が優先される場合だけ保存 row を更新する statement.
    """
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
    """候補が保存済み performance best より優先される条件を構築する.

    Args:
        command (UpsertBeatmapPerformanceBest): PP、送信時刻、score ID による候補順位.

    Returns:
        ColumnElement[bool]: PP 降順、送信時刻昇順、score ID 昇順の優先順を表す条件.
    """
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
    """指定 performance best projection slice を削除する DELETE statement を構築する.

    Args:
        slice_ (BeatmapPerformanceBestProjectionSlice): user または beatmap ID 群で表す置換範囲.

    Returns:
        Delete: slice に属する performance best row だけを削除する statement.
    """
    statement = delete(BeatmapPerformanceBestModel)
    if isinstance(slice_, BeatmapPerformanceBestUserProjectionSlice):
        return statement.where(BeatmapPerformanceBestModel.user_id == slice_.user_id)
    return statement.where(BeatmapPerformanceBestModel.beatmap_id.in_(slice_.beatmap_ids))


def _delete_scope_statement(scope: BeatmapPerformanceBestScope) -> Delete:
    """完全一致の performance best scope を削除する DELETE statement を構築する.

    Args:
        scope (BeatmapPerformanceBestScope): 削除する user、beatmap、ruleset、playstyle の scope.

    Returns:
        Delete: scope の natural key に一致する row だけを削除する statement.
    """
    return delete(BeatmapPerformanceBestModel).where(*_scope_conditions(scope))


def _slice_contains(
    slice_: BeatmapPerformanceBestProjectionSlice,
    scope: BeatmapPerformanceBestScope,
) -> bool:
    """Projection slice が候補 scope を含むか判定する.

    Args:
        slice_ (BeatmapPerformanceBestProjectionSlice): user または beatmap ID 群で表す対象範囲.
        scope (BeatmapPerformanceBestScope): 置換候補の performance best scope.

    Returns:
        bool: scope が slice に含まれる場合は True. それ以外は False.
    """
    if isinstance(slice_, BeatmapPerformanceBestUserProjectionSlice):
        return scope.user_id == slice_.user_id
    return scope.beatmap_id in slice_.beatmap_ids


def _model_to_domain(model: BeatmapPerformanceBestModel) -> BeatmapPerformanceBest:
    """SQLAlchemy performance best model を domain value へ変換する.

    Args:
        model (BeatmapPerformanceBestModel): 永続化済みの performance best row.

    Returns:
        BeatmapPerformanceBest: ruleset と playstyle を復元した domain value.

    Raises:
        ValueError: 保存済みの ruleset または playstyle が不正な場合.
    """
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

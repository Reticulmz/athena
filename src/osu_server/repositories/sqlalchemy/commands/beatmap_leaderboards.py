"""SQLAlchemy command-side beatmap leaderboard projection repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBest,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    BeatmapLeaderboardUserScope,
)
from osu_server.repositories.sqlalchemy.models.beatmap_leaderboard import (
    BeatmapLeaderboardUserBestModel,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.dialects.postgresql.dml import Insert
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.dml import Delete
    from sqlalchemy.sql.elements import ColumnElement

    from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
        BeatmapLeaderboardProjectionSlice,
        UpsertBeatmapLeaderboardUserBest,
    )


class SQLAlchemyBeatmapLeaderboardCommandRepository:
    """UoW 所有 session で raw Mod scope best を永続化する repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def get_user_best(
        self,
        scope: BeatmapLeaderboardUserBestScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """指定 scope のユーザー最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserBestScope): 検索する raw Mod scope.

        Returns:
            BeatmapLeaderboardUserBest | None: 保存行. 未登録時は None.
        """
        model = (await self._session.execute(_select_by_scope(scope))).scalar_one_or_none()
        return (
            _model_to_domain(model) if isinstance(model, BeatmapLeaderboardUserBestModel) else None
        )

    async def get_global_user_best(
        self,
        scope: BeatmapLeaderboardUserScope,
    ) -> BeatmapLeaderboardUserBest | None:
        """全 raw Mod scope からユーザーの Global 最高 score を返す.

        Args:
            scope (BeatmapLeaderboardUserScope): Mod を含まない検索 scope.

        Returns:
            BeatmapLeaderboardUserBest | None: Global 最高 score. 未登録時は None.
        """
        statement = (
            select(BeatmapLeaderboardUserBestModel)
            .where(*_global_scope_conditions(scope))
            .order_by(
                BeatmapLeaderboardUserBestModel.score.desc(),
                BeatmapLeaderboardUserBestModel.submitted_at.asc(),
                BeatmapLeaderboardUserBestModel.score_id.asc(),
            )
            .limit(1)
        )
        model = (await self._session.execute(statement)).scalar_one_or_none()
        return (
            _model_to_domain(model) if isinstance(model, BeatmapLeaderboardUserBestModel) else None
        )

    async def upsert_if_better(
        self,
        command: UpsertBeatmapLeaderboardUserBest,
    ) -> BeatmapLeaderboardUserBest:
        """候補が現在値より上位の場合だけ upsert する.

        Args:
            command (UpsertBeatmapLeaderboardUserBest): 比較対象の候補 score.

        Returns:
            BeatmapLeaderboardUserBest: upsert 後の保存行.

        Raises:
            RuntimeError: upsert 後の保存行を取得できない場合.
        """
        _ = await self._session.execute(_upsert_if_better_statement(command))
        model = (
            await self._session.execute(_select_by_scope(command.scope).with_for_update())
        ).scalar_one_or_none()

        if isinstance(model, BeatmapLeaderboardUserBestModel):
            return _model_to_domain(model)
        msg = "beatmap leaderboard upsert did not return a persisted projection"
        raise RuntimeError(msg)

    async def replace_projection_slice(
        self,
        slice_: BeatmapLeaderboardProjectionSlice,
        rows: Iterable[UpsertBeatmapLeaderboardUserBest],
    ) -> None:
        """再構築対象 slice の Mod別 best を置換する.

        Args:
            slice_ (BeatmapLeaderboardProjectionSlice): user または Beatmap の対象範囲.
            rows (Iterable[UpsertBeatmapLeaderboardUserBest]): 置換後の score 群.

        Returns:
            None: 置換が完了したことを示す.

        Raises:
            ValueError: 対象外 scope の行が含まれる場合.
        """
        rows_to_insert = tuple(rows)
        for row in rows_to_insert:
            if not _slice_contains(slice_, row.scope):
                msg = "replacement row is outside projection slice"
                raise ValueError(msg)

        _ = await self._session.execute(_delete_slice_statement(slice_))
        for row in rows_to_insert:
            _ = await self.upsert_if_better(row)


def _select_by_scope(
    scope: BeatmapLeaderboardUserBestScope,
) -> Select[tuple[BeatmapLeaderboardUserBestModel]]:
    return select(BeatmapLeaderboardUserBestModel).where(*_scope_conditions(scope))


def _scope_conditions(
    scope: BeatmapLeaderboardUserBestScope,
) -> tuple[ColumnElement[bool], ...]:
    return (
        BeatmapLeaderboardUserBestModel.beatmap_id == scope.beatmap_id,
        BeatmapLeaderboardUserBestModel.beatmap_checksum == scope.beatmap_checksum,
        BeatmapLeaderboardUserBestModel.ruleset == scope.ruleset.value,
        BeatmapLeaderboardUserBestModel.playstyle == scope.playstyle.value,
        BeatmapLeaderboardUserBestModel.user_id == scope.user_id,
        BeatmapLeaderboardUserBestModel.mods == scope.mods.to_persistence_bitmask(),
    )


def _global_scope_conditions(
    scope: BeatmapLeaderboardUserScope,
) -> tuple[ColumnElement[bool], ...]:
    return (
        BeatmapLeaderboardUserBestModel.beatmap_id == scope.beatmap_id,
        BeatmapLeaderboardUserBestModel.beatmap_checksum == scope.beatmap_checksum,
        BeatmapLeaderboardUserBestModel.ruleset == scope.ruleset.value,
        BeatmapLeaderboardUserBestModel.playstyle == scope.playstyle.value,
        BeatmapLeaderboardUserBestModel.user_id == scope.user_id,
    )


def _upsert_if_better_statement(command: UpsertBeatmapLeaderboardUserBest) -> Insert:
    insert_statement = insert(BeatmapLeaderboardUserBestModel).values(
        beatmap_id=command.scope.beatmap_id,
        beatmap_checksum=command.scope.beatmap_checksum,
        ruleset=command.scope.ruleset.value,
        playstyle=command.scope.playstyle.value,
        user_id=command.scope.user_id,
        mods=command.scope.mods.to_persistence_bitmask(),
        score_id=command.score_id,
        score=command.rank_key.score,
        submitted_at=command.rank_key.submitted_at,
    )
    return insert_statement.on_conflict_do_update(
        index_elements=[
            BeatmapLeaderboardUserBestModel.beatmap_id,
            BeatmapLeaderboardUserBestModel.ruleset,
            BeatmapLeaderboardUserBestModel.playstyle,
            BeatmapLeaderboardUserBestModel.user_id,
            BeatmapLeaderboardUserBestModel.mods,
        ],
        set_={
            "beatmap_checksum": command.scope.beatmap_checksum,
            "score_id": command.score_id,
            "score": command.rank_key.score,
            "submitted_at": command.rank_key.submitted_at,
            "updated_at": func.now(),
        },
        where=or_(
            BeatmapLeaderboardUserBestModel.beatmap_checksum != command.scope.beatmap_checksum,
            _candidate_beats_current(command.rank_key),
        ),
    )


def _candidate_beats_current(rank_key: ScoreRankKey) -> ColumnElement[bool]:
    return or_(
        BeatmapLeaderboardUserBestModel.score < rank_key.score,
        and_(
            BeatmapLeaderboardUserBestModel.score == rank_key.score,
            BeatmapLeaderboardUserBestModel.submitted_at > rank_key.submitted_at,
        ),
        and_(
            BeatmapLeaderboardUserBestModel.score == rank_key.score,
            BeatmapLeaderboardUserBestModel.submitted_at == rank_key.submitted_at,
            BeatmapLeaderboardUserBestModel.score_id > rank_key.score_id,
        ),
    )


def _delete_slice_statement(slice_: BeatmapLeaderboardProjectionSlice) -> Delete:
    statement = delete(BeatmapLeaderboardUserBestModel)
    if isinstance(slice_, BeatmapLeaderboardUserProjectionSlice):
        return statement.where(BeatmapLeaderboardUserBestModel.user_id == slice_.user_id)
    return statement.where(BeatmapLeaderboardUserBestModel.beatmap_id.in_(slice_.beatmap_ids))


def _slice_contains(
    slice_: BeatmapLeaderboardProjectionSlice,
    scope: BeatmapLeaderboardUserBestScope,
) -> bool:
    if isinstance(slice_, BeatmapLeaderboardUserProjectionSlice):
        return scope.user_id == slice_.user_id
    return scope.beatmap_id in slice_.beatmap_ids


def _model_to_domain(model: BeatmapLeaderboardUserBestModel) -> BeatmapLeaderboardUserBest:
    return BeatmapLeaderboardUserBest(
        id=model.id,
        scope=BeatmapLeaderboardUserBestScope(
            beatmap_id=model.beatmap_id,
            beatmap_checksum=model.beatmap_checksum,
            ruleset=Ruleset(model.ruleset),
            playstyle=Playstyle(model.playstyle),
            user_id=model.user_id,
            mods=ModCombination.from_persistence_bitmask(model.mods),
        ),
        score_id=model.score_id,
        rank_key=ScoreRankKey(
            score=model.score,
            submitted_at=model.submitted_at,
            score_id=model.score_id,
        ),
    )

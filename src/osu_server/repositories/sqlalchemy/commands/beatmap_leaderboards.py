"""SQLAlchemy を用いて beatmap leaderboard projection を永続化する command repository."""

from __future__ import annotations

from hashlib import blake2b
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

_DUPLICATE_SCORE_ID_MESSAGE = "score_id is already used by another leaderboard projection row"
_PROJECTION_REBUILD_LOCK_NAMESPACE = "beatmap_leaderboard_user_bests:rebuild"

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
    """UoW 所有 session で raw Mod scope の best projection を永続化する repository.

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

    async def lock_rebuild(self) -> None:
        """Projection rebuild 用の exclusive transaction lock を取得する.

        Returns:
            None: transaction終了まで全submit projection更新を停止したことを示す.
        """
        statement = select(func.pg_advisory_xact_lock(_projection_rebuild_lock_key()))
        _ = await self._session.execute(statement)

    async def lock_scope(self, scope: BeatmapLeaderboardUserScope) -> None:
        """Submit 更新を rebuild および同一 scope 更新と transaction 内で直列化する.

        Args:
            scope (BeatmapLeaderboardUserScope): Modを含まないserialization scope.

        Returns:
            None: shared rebuild guardとexclusive scope lockを取得したことを示す.
        """
        rebuild_guard = select(func.pg_advisory_xact_lock_shared(_projection_rebuild_lock_key()))
        scope_lock = select(func.pg_advisory_xact_lock(_scope_lock_key(scope)))
        _ = await self._session.execute(rebuild_guard)
        _ = await self._session.execute(scope_lock)

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
            ValueError: 同じscore_idが別projection rowで使用済みの場合.
            RuntimeError: upsert 後の保存行を取得できない場合.
        """
        score_id_lock = select(func.pg_advisory_xact_lock(_score_id_lock_key(command.score_id)))
        _ = await self._session.execute(score_id_lock)
        score_id_owner = (
            await self._session.execute(
                select(BeatmapLeaderboardUserBestModel).where(
                    BeatmapLeaderboardUserBestModel.score_id == command.score_id
                )
            )
        ).scalar_one_or_none()
        if isinstance(score_id_owner, BeatmapLeaderboardUserBestModel) and not _model_has_scope(
            score_id_owner,
            command.scope,
        ):
            raise ValueError(_DUPLICATE_SCORE_ID_MESSAGE)

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
        """再構築対象 slice の Mod 別 best を置換する.

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
    """Raw Mod を含む完全一致 scope の SELECT statement を構築する.

    Args:
        scope (BeatmapLeaderboardUserBestScope): 検索対象の projection natural key.

    Returns:
        Select[tuple[BeatmapLeaderboardUserBestModel]]: scope が一致する保存行だけを返す statement.
    """
    return select(BeatmapLeaderboardUserBestModel).where(*_scope_conditions(scope))


def _scope_conditions(
    scope: BeatmapLeaderboardUserBestScope,
) -> tuple[ColumnElement[bool], ...]:
    """Raw Mod を含む projection scope の絞り込み条件を返す.

    Args:
        scope (BeatmapLeaderboardUserBestScope): 比較する beatmap、ruleset、user、Mod の scope.

    Returns:
        tuple[ColumnElement[bool], ...]: natural key の各列を完全一致で比較する条件列.
    """
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
    """Mod を除く Global best 検索用の projection scope 条件を返す.

    Args:
        scope (BeatmapLeaderboardUserScope): Mod をまたいで比較する beatmap と user の scope.

    Returns:
        tuple[ColumnElement[bool], ...]: Mod 列を含めず natural key を比較する条件列.
    """
    return (
        BeatmapLeaderboardUserBestModel.beatmap_id == scope.beatmap_id,
        BeatmapLeaderboardUserBestModel.beatmap_checksum == scope.beatmap_checksum,
        BeatmapLeaderboardUserBestModel.ruleset == scope.ruleset.value,
        BeatmapLeaderboardUserBestModel.playstyle == scope.playstyle.value,
        BeatmapLeaderboardUserBestModel.user_id == scope.user_id,
    )


def _upsert_if_better_statement(command: UpsertBeatmapLeaderboardUserBest) -> Insert:
    """候補が既存 rank key を上回る場合だけ更新する UPSERT statement を構築する.

    Args:
        command (UpsertBeatmapLeaderboardUserBest): 保存する scope、score ID、rank key の候補.

    Returns:
        Insert: natural key 競合時に freshness または順位が改善した行だけを更新する statement.
    """
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
    """候補の rank key が保存済み row より優先される条件を構築する.

    Args:
        rank_key (ScoreRankKey): score、送信時刻、score ID による候補順位.

    Returns:
        ColumnElement[bool]: score 降順、submitted_at 昇順、score ID 昇順の優先順を表す条件.
    """
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


def _scope_lock_key(scope: BeatmapLeaderboardUserScope) -> int:
    """Leaderboard 更新 scope を PostgreSQL advisory lock key へ変換する.

    Args:
        scope (BeatmapLeaderboardUserScope): user、beatmap、ruleset、playstyle を含む lock scope.

    Returns:
        int: `pg_advisory_xact_lock`へ渡すsigned 64-bit key.

    Notes:
        同じ scope は同じ key を返す. Mod と checksum は serialization identity に含めない.
        構築済み scope を受け取る前提でこの helper 自体は独自の例外を送出しない.
    """
    namespace = (
        "beatmap_leaderboard_user_bests:"
        f"{scope.user_id}:{scope.beatmap_id}:{scope.ruleset.value}:{scope.playstyle.value}"
    )
    return _advisory_lock_key(namespace)


def _score_id_lock_key(score_id: int) -> int:
    """Projection の score ID を PostgreSQL advisory lock key へ変換する.

    Args:
        score_id (int): 一意性を直列化する source score ID.

    Returns:
        int: `pg_advisory_xact_lock`へ渡すsigned 64-bit key.

    Notes:
        同じ score ID は同じ key を返し transaction 終了まで所有確認と upsert を直列化する.
    """
    return _advisory_lock_key(f"beatmap_leaderboard_user_bests:score_id:{score_id}")


def _projection_rebuild_lock_key() -> int:
    """全 projection rebuild で共有する PostgreSQL advisory lock key を返す.

    Returns:
        int: submitがshared, rebuildがexclusiveで取得するsigned 64-bit key.
    """
    return _advisory_lock_key(_PROJECTION_REBUILD_LOCK_NAMESPACE)


def _advisory_lock_key(namespace: str) -> int:
    """Advisory lock namespace を安定した signed 64-bit key へ変換する.

    Args:
        namespace (str): repository 内で一意な lock namespace.

    Returns:
        int: PostgreSQL bigint 範囲の deterministic advisory lock key.
    """
    return int.from_bytes(
        blake2b(namespace.encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )


def _delete_slice_statement(slice_: BeatmapLeaderboardProjectionSlice) -> Delete:
    """指定 projection slice の保存行を削除する DELETE statement を構築する.

    Args:
        slice_ (BeatmapLeaderboardProjectionSlice): user または beatmap ID 群で表す再構築範囲.

    Returns:
        Delete: slice に含まれる projection row だけを削除する statement.
    """
    statement = delete(BeatmapLeaderboardUserBestModel)
    if isinstance(slice_, BeatmapLeaderboardUserProjectionSlice):
        return statement.where(BeatmapLeaderboardUserBestModel.user_id == slice_.user_id)
    return statement.where(BeatmapLeaderboardUserBestModel.beatmap_id.in_(slice_.beatmap_ids))


def _slice_contains(
    slice_: BeatmapLeaderboardProjectionSlice,
    scope: BeatmapLeaderboardUserBestScope,
) -> bool:
    """Projection slice が候補 scope を含むか判定する.

    Args:
        slice_ (BeatmapLeaderboardProjectionSlice): user または beatmap ID 群で表す対象範囲.
        scope (BeatmapLeaderboardUserBestScope): 置換候補の projection natural key.

    Returns:
        bool: candidate scope が slice に含まれる場合は True. それ以外は False.
    """
    if isinstance(slice_, BeatmapLeaderboardUserProjectionSlice):
        return scope.user_id == slice_.user_id
    return scope.beatmap_id in slice_.beatmap_ids


def _model_has_scope(
    model: BeatmapLeaderboardUserBestModel,
    scope: BeatmapLeaderboardUserBestScope,
) -> bool:
    """保存行がprojection natural key上で指定scopeと一致するか判定する.

    Args:
        model (BeatmapLeaderboardUserBestModel): score_idを現在所有する保存行.
        scope (BeatmapLeaderboardUserBestScope): upsert先のprojection scope.

    Returns:
        bool: checksumを除くnatural keyが一致する場合はTrue.

    Notes:
        beatmap_checksumは置換可能なfreshness属性であり、row identityには含めない.
    """
    return (
        model.beatmap_id == scope.beatmap_id
        and model.ruleset == scope.ruleset.value
        and model.playstyle == scope.playstyle.value
        and model.user_id == scope.user_id
        and model.mods == scope.mods.to_persistence_bitmask()
    )


def _model_to_domain(model: BeatmapLeaderboardUserBestModel) -> BeatmapLeaderboardUserBest:
    """SQLAlchemy projection model を domain の leaderboard best へ変換する.

    Args:
        model (BeatmapLeaderboardUserBestModel): 永続化済みの projection row.

    Returns:
        BeatmapLeaderboardUserBest: ruleset、playstyle、Mod、rank key を復元した domain value.

    Raises:
        ValueError: 保存済みの ruleset、playstyle、または Mod bitmask が不正な場合.
    """
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

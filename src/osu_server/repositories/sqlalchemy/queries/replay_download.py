"""SQLAlchemy replay download query repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, func, literal, select

from osu_server.domain.identity.leaderboard_visibility import (
    LEADERBOARD_VISIBLE_PERMISSION_MASK,
)
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadAvailableReplayCandidate,
    ReplayDownloadCandidate,
    ReplayDownloadCandidateQuery,
    ReplayDownloadHiddenScoreCandidate,
    ReplayDownloadMissingReplayCandidate,
    ReplayDownloadScoreNotFoundCandidate,
)
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.score import ReplayModel, ScoreModel

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.sql.base import Executable
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.selectable import Subquery

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory


class SQLAlchemyReplayDownloadQueryRepository:
    """Replay download candidate を SQLAlchemy metadata から投影する.

    引数:
        session_factory: Short read session を生成する factory.

    戻り値:
        Class のため戻り値はない.

    例外:
        なし.

    制約:
        Raw replay bytes, blob storage key, filesystem path は読まない.
        Score, owner visibility, replay attachment metadata だけを参照する.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """Repository を short read session factory で初期化する.

        引数:
            session_factory: Query ごとに閉じる SQLAlchemy read session factory.

        戻り値:
            None.

        例外:
            なし.

        制約:
            Factory は保持するだけで session を先行生成しない.
        """
        self._session_factory = session_factory

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Score id と ruleset から replay download candidate branch を返す.

        引数:
            query: Parsed score id と Stable ruleset scope.

        戻り値:
            Score not found, hidden score, missing replay, available replay のいずれか.

        例外:
            SQLAlchemy session または database の read 例外を送出する可能性がある.

        制約:
            1 回の short read session で metadata だけを投影する. Blob object の
            storage key や raw bytes は読まない.
        """
        async with self._session_factory() as session:
            row = cast(
                "Mapping[str, object] | None",
                (
                    await session.execute(
                        _candidate_statement(query),
                    )
                )
                .mappings()
                .one_or_none(),
            )

        if row is None:
            return ReplayDownloadScoreNotFoundCandidate()

        return _candidate_from_mapping(row)


def _candidate_statement(query: ReplayDownloadCandidateQuery) -> Executable:
    role_permissions = _role_permissions_subquery()
    replay_download_visible = and_(
        ScoreModel.passed.is_(True),
        ScoreModel.leaderboard_eligible_at_submission.is_(True),
        _leaderboard_visible_condition(role_permissions),
    )
    return (
        select(
            ScoreModel.id.label("score_id"),
            replay_download_visible.label("replay_download_visible"),
            ReplayModel.blob_id.label("blob_id"),
            ReplayModel.checksum_sha256.label("checksum"),
            ReplayModel.byte_size.label("byte_size"),
        )
        .select_from(ScoreModel)
        .outerjoin(ReplayModel, ReplayModel.score_id == ScoreModel.id)
        .outerjoin(role_permissions, role_permissions.c.user_id == ScoreModel.user_id)
        .where(
            ScoreModel.id == query.score_id,
            ScoreModel.ruleset == query.ruleset.value,
        )
        .limit(1)
    )


def _role_permissions_subquery() -> Subquery:
    return (
        select(
            UserRoleModel.user_id.label("user_id"),
            func.coalesce(func.bit_or(RoleModel.permissions), 0).label("permissions"),
        )
        .select_from(UserRoleModel)
        .join(RoleModel, RoleModel.id == UserRoleModel.role_id)
        .group_by(UserRoleModel.user_id)
        .subquery("role_permissions")
    )


def _leaderboard_visible_condition(role_permissions: Subquery) -> ColumnElement[bool]:
    permissions = cast(
        "ColumnElement[int]",
        func.coalesce(role_permissions.c.permissions, 0),
    )
    return permissions.bitwise_and(LEADERBOARD_VISIBLE_PERMISSION_MASK) == literal(
        LEADERBOARD_VISIBLE_PERMISSION_MASK
    )


def _candidate_from_mapping(row: Mapping[str, object]) -> ReplayDownloadCandidate:
    if not _bool_value(row, "replay_download_visible"):
        return ReplayDownloadHiddenScoreCandidate()

    blob_id = row.get("blob_id")
    if blob_id is None:
        return ReplayDownloadMissingReplayCandidate()

    return ReplayDownloadAvailableReplayCandidate(
        blob_id=_int_value(row, "blob_id"),
        checksum=_str_value(row, "checksum"),
        byte_size=_int_value(row, "byte_size"),
    )


def _bool_value(mapping: Mapping[str, object], key: str) -> bool:
    value = mapping[key]
    if not isinstance(value, bool):
        msg = f"{key} must be a bool"
        raise TypeError(msg)
    return value


def _int_value(mapping: Mapping[str, object], key: str) -> int:
    value = mapping[key]
    if not isinstance(value, int):
        msg = f"{key} must be an int"
        raise TypeError(msg)
    return value


def _str_value(mapping: Mapping[str, object], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str):
        msg = f"{key} must be a str"
        raise TypeError(msg)
    return value


__all__ = ["SQLAlchemyReplayDownloadQueryRepository"]

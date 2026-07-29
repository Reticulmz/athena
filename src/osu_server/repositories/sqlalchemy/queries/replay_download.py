"""SQLAlchemyからreplay download可否とmetadataをread-onlyで判定するquery repositoryを提供する."""

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
    """replay download candidateをSQLAlchemy metadataから投影する.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.

    Notes:
        raw replay bytes,blob storage key,filesystem pathは読まず,Score,owner visibility,
        replay attachment metadataだけを参照する.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """短命なread session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用read session factory.

        Returns:
            None: 読み取り用session factoryを保持したrepository instanceを初期化する.

        Notes:
            factoryは保持するだけでsessionを先行生成しない.
        """
        self._session_factory = session_factory

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Score IDとrulesetからreplay download candidate branchを返す.

        Args:
            query (ReplayDownloadCandidateQuery): parsed Score IDとstable ruleset scope.

        Returns:
            ReplayDownloadCandidate: score not found,hidden score,missing replay,
                available replayのいずれか.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            KeyError: available replay rowに必要なfieldがない場合.
            TypeError: available replay rowのfield型が期待値と異なる場合.

        Notes:
            1回のshort read sessionでmetadataだけを投影する.
            Blob objectのstorage keyやraw bytesは読まない.
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
    """Replay download可否とattachment metadataを取得するstatementを構築する.

    Args:
        query (ReplayDownloadCandidateQuery): 検索するScore IDとruleset scope.

    Returns:
        Executable: Score,owner visibility,replay attachment metadataを最大1rowで返すSELECT.

    Notes:
        passedかつleaderboard eligibleで権限上表示可能なScoreだけをdownload可能としてlabelし,
        Blob tableやstorage detailはjoinしない.
    """
    role_permissions = _role_permissions_subquery()
    replay_download_visible = and_(
        ScoreModel.passed.is_(True),
        ScoreModel.leaderboard_eligible_at_submission.is_(True),
        _leaderboard_visible_condition(role_permissions),
    )
    return (
        select(
            ScoreModel.id.label("score_id"),
            ScoreModel.user_id.label("score_owner_user_id"),
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
    """Userごとの集約Role permissionを返すsubqueryを構築する.

    Returns:
        Subquery: user_idと割り当てRole permissionのbitwise ORを返すsubquery.

    Notes:
        Roleが割り当てられていないUserのpermission補完は呼び出し側のcoalesceで行う.
    """
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
    """集約Role permissionがleaderboard表示要件を満たす条件を構築する.

    Args:
        role_permissions (Subquery): user_idごとの集約permissionを返すsubquery.

    Returns:
        ColumnElement[bool]: LEADERBOARD_VISIBLE_PERMISSION_MASKの全bitを持つかを判定するSQL条件.

    Notes:
        permissionがNULLの場合は0として扱う.
    """
    permissions = cast(
        "ColumnElement[int]",
        func.coalesce(role_permissions.c.permissions, 0),
    )
    return permissions.bitwise_and(LEADERBOARD_VISIBLE_PERMISSION_MASK) == literal(
        LEADERBOARD_VISIBLE_PERMISSION_MASK
    )


def _candidate_from_mapping(row: Mapping[str, object]) -> ReplayDownloadCandidate:
    """SQL mapping rowをreplay download candidate branchへ変換する.

    Args:
        row (Mapping[str, object]): Score,visibility,replay attachment metadataを含むmapping row.

    Returns:
        ReplayDownloadCandidate: visibilityとattachment有無に対応するcandidate branch.

    Raises:
        KeyError: 必須fieldがmappingに存在しない場合.
        TypeError: 必須fieldの型が期待値と異なる場合.

    Notes:
        hidden scoreはattachmentがあってもHIDDEN_SCOREを優先する.
        visible scoreでblob_idがない場合はMISSING_REPLAYを返す.
    """
    if not _bool_value(row, "replay_download_visible"):
        return ReplayDownloadHiddenScoreCandidate()

    blob_id = row.get("blob_id")
    if blob_id is None:
        return ReplayDownloadMissingReplayCandidate()

    return ReplayDownloadAvailableReplayCandidate(
        score_id=_int_value(row, "score_id"),
        score_owner_user_id=_int_value(row, "score_owner_user_id"),
        blob_id=_int_value(row, "blob_id"),
        checksum=_str_value(row, "checksum"),
        byte_size=_int_value(row, "byte_size"),
    )


def _bool_value(mapping: Mapping[str, object], key: str) -> bool:
    """mappingからbool型の必須fieldを取得する.

    Args:
        mapping (Mapping[str, object]): SQLAlchemy mapping row.
        key (str): 取得する必須field名.

    Returns:
        bool: keyに対応するbool値.

    Raises:
        KeyError: keyがmappingに存在しない場合.
        TypeError: keyに対応する値がboolではない場合.
    """
    value = mapping[key]
    if not isinstance(value, bool):
        msg = f"{key} must be a bool"
        raise TypeError(msg)
    return value


def _int_value(mapping: Mapping[str, object], key: str) -> int:
    """mappingからint型の必須fieldを取得する.

    Args:
        mapping (Mapping[str, object]): SQLAlchemy mapping row.
        key (str): 取得する必須field名.

    Returns:
        int: keyに対応するint値.

    Raises:
        KeyError: keyがmappingに存在しない場合.
        TypeError: keyに対応する値がintではない場合.
    """
    value = mapping[key]
    if not isinstance(value, int):
        msg = f"{key} must be an int"
        raise TypeError(msg)
    return value


def _str_value(mapping: Mapping[str, object], key: str) -> str:
    """mappingからstr型の必須fieldを取得する.

    Args:
        mapping (Mapping[str, object]): SQLAlchemy mapping row.
        key (str): 取得する必須field名.

    Returns:
        str: keyに対応するstr値.

    Raises:
        KeyError: keyがmappingに存在しない場合.
        TypeError: keyに対応する値がstrではない場合.
    """
    value = mapping[key]
    if not isinstance(value, str):
        msg = f"{key} must be a str"
        raise TypeError(msg)
    return value


__all__ = ["SQLAlchemyReplayDownloadQueryRepository"]

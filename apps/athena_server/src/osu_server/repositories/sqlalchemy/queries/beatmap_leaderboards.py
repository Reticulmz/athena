"""SQLAlchemyからmod別Beatmap Leaderboardをread-onlyで構築するquery repositoryを提供する."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from sqlalchemy import String, and_, case, func, literal, select
from sqlalchemy import cast as sql_cast

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.identity.leaderboard_visibility import (
    LEADERBOARD_VISIBLE_PERMISSION_MASK,
)
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.personal_best import (
    LeaderboardCategory,
    country_leaderboard_is_available,
    friends_leaderboard_is_available,
)
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardRow,
    LeaderboardReadScope,
    ScoreHitCounts,
)
from osu_server.repositories.sqlalchemy.models.beatmap import BeatmapModel
from osu_server.repositories.sqlalchemy.models.beatmap_leaderboard import (
    BeatmapLeaderboardUserBestModel,
)
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.score import ReplayModel, ScoreModel
from osu_server.repositories.sqlalchemy.models.score_performance import (
    ScorePerformanceCalculationModel,
)
from osu_server.repositories.sqlalchemy.models.user import UserModel

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.sql.base import Executable
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.selectable import Select, Subquery

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_MAX_QUERY_LIMIT = 50
_VISIBLE_BEATMAP_STATUS_VALUES = (
    BeatmapRankStatus.RANKED.value,
    BeatmapRankStatus.APPROVED.value,
    BeatmapRankStatus.LOVED.value,
    BeatmapRankStatus.QUALIFIED.value,
)
_PP_VISIBLE_BEATMAP_STATUS_VALUES = (
    BeatmapRankStatus.RANKED.value,
    BeatmapRankStatus.APPROVED.value,
)


class SQLAlchemyBeatmapLeaderboardQueryRepository:
    """Mod別 user-best projection から Beatmap Leaderboard を構築する repository.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.

    Notes:
        projectionで候補を絞り,表示fieldはsource Scoreから取得する.
    """

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Notes:
            初期化時にはsessionを生成せず,leaderboard projectionやScoreを変更しない.
        """
        self._session_factory: SQLAlchemyQuerySessionFactory = session_factory

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        """指定scopeの上位行をdeterministicな順位で返す.

        Args:
            scope (LeaderboardReadScope): Beatmapとcategory filterを含むread scope.
            limit (int): 取得上限. repository上限を超える値は切り詰める.

        Returns:
            tuple[BeatmapLeaderboardRow, ...]: User別最高Scoreの順位付き行.
            上限が0以下または候補がない場合は空tuple.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            TypeError: SQL result rowの必須field型が期待値と異なる場合.
            ValueError: SELECTED_MODS categoryでscope.selected_modsがNoneの場合,または結果rowの
                ruleset,playstyle,displayed mods bitmaskをdomain valueへ変換できない場合.

        Notes:
            limitは0から50へclampし,上位候補の順位はScore,submitted_at,Score IDで決定する.
        """
        capped_limit = min(max(limit, 0), _MAX_QUERY_LIMIT)
        if capped_limit == 0:
            return ()

        ranked_candidates = _ranked_candidates_subquery(scope)
        statement = (
            _select_ranked_candidate_rows(ranked_candidates)
            .where(ranked_candidates.c.rank <= capped_limit)
            .order_by(ranked_candidates.c.rank.asc())
        )
        return await self._fetch_rows(statement)

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        """viewerのpersonal bestと全体順位を返す.

        Args:
            scope (LeaderboardReadScope): Beatmapとcategory filterを含むread scope.
            viewer_user_id (int): personal bestを取得するUser ID.

        Returns:
            BeatmapLeaderboardRow | None: 対象Scoreの順位付き行. 候補がない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            TypeError: SQL result rowの必須field型が期待値と異なる場合.
            ValueError: SELECTED_MODS categoryでscope.selected_modsがNoneの場合,または結果rowの
                ruleset,playstyle,displayed mods bitmaskをdomain valueへ変換できない場合.

        Notes:
            top rowsと同じfiltered windowを使うため,返すrankは全体leaderboardのrankと一致する.
        """
        ranked_candidates = _ranked_candidates_subquery(scope)
        statement = (
            _select_ranked_candidate_rows(ranked_candidates)
            .where(ranked_candidates.c.user_id == viewer_user_id)
            .limit(1)
        )
        rows = await self._fetch_rows(statement)
        return rows[0] if rows else None

    async def _fetch_rows(self, statement: Executable) -> tuple[BeatmapLeaderboardRow, ...]:
        """statementを短命sessionで実行し,mapping rowをleaderboard rowへ変換する.

        Args:
            statement (Executable): leaderboard fieldを返す実行可能なSELECT statement.

        Returns:
            tuple[BeatmapLeaderboardRow, ...]: statement結果をdomain rowへ変換したtuple.

        Raises:
            SQLAlchemyError: statementの実行またはrow取得に失敗した場合.
            KeyError: SQL result rowに必須fieldがない場合.
            TypeError: SQL result rowの必須field型が期待値と異なる場合.
            ValueError: 結果rowのruleset,playstyle,またはdisplayed mods bitmaskをdomain valueへ
                変換できない場合.

        Notes:
            sessionはこのmethod内で開閉し,statementとrowを変更しない.
        """
        async with self._session_factory() as session:
            result = await session.execute(statement)
            rows = result.mappings().all()
        return tuple(_row_from_mapping(cast("object", row)) for row in rows)


def _user_best_score_ids_subquery(scope: LeaderboardReadScope) -> Subquery:
    """scope内でUserごとの最高Score IDだけを残すsubqueryを構築する.

    Args:
        scope (LeaderboardReadScope): Beatmap,ruleset,playstyle,category filterを含むread scope.

    Returns:
        Subquery: user_best_score_idsという名前で最高Score IDを返すsubquery.

    Raises:
        ValueError: SELECTED_MODS categoryでscope.selected_modsがNoneの場合.

    Notes:
        raw mods bitmaskはidentityのため,DT/NC,SD/PF,Mirrorを正規化せず完全一致で比較する.
    """
    candidate_filters: list[ColumnElement[bool]] = [
        BeatmapLeaderboardUserBestModel.beatmap_id == scope.beatmap_id,
        BeatmapLeaderboardUserBestModel.beatmap_checksum == scope.beatmap_checksum,
        BeatmapLeaderboardUserBestModel.ruleset == scope.ruleset.value,
        BeatmapLeaderboardUserBestModel.playstyle == scope.playstyle.value,
        ScoreModel.beatmap_id == BeatmapLeaderboardUserBestModel.beatmap_id,
        ScoreModel.beatmap_checksum == BeatmapLeaderboardUserBestModel.beatmap_checksum,
        ScoreModel.ruleset == BeatmapLeaderboardUserBestModel.ruleset,
        ScoreModel.playstyle == BeatmapLeaderboardUserBestModel.playstyle,
        ScoreModel.user_id == BeatmapLeaderboardUserBestModel.user_id,
        ScoreModel.mods == BeatmapLeaderboardUserBestModel.mods,
        ScoreModel.passed.is_(True),
        ScoreModel.leaderboard_eligible_at_submission.is_(True),
    ]
    if scope.category is LeaderboardCategory.SELECTED_MODS:
        selected_mods = scope.selected_mods
        if selected_mods is None:
            msg = "selected-mods scope requires selected_mods"
            raise ValueError(msg)
        # raw bitmask自体がidentityであり, DT/NC, SD/PF, Mirrorを正規化しない.
        candidate_filters.append(
            BeatmapLeaderboardUserBestModel.mods == selected_mods.to_persistence_bitmask()
        )

    user_rank = func.row_number().over(
        partition_by=BeatmapLeaderboardUserBestModel.user_id,
        order_by=(
            ScoreModel.score.desc(),
            ScoreModel.submitted_at.asc(),
            ScoreModel.id.asc(),
        ),
    )
    ranked_user_scores = (
        select(
            BeatmapLeaderboardUserBestModel.score_id.label("score_id"),
            user_rank.label("user_rank"),
        )
        .join(ScoreModel, ScoreModel.id == BeatmapLeaderboardUserBestModel.score_id)
        .where(*candidate_filters)
        .subquery("ranked_user_scores")
    )
    return (
        select(ranked_user_scores.c.score_id)
        .where(ranked_user_scores.c.user_rank == 1)
        .subquery("user_best_score_ids")
    )


def _ranked_candidates_subquery(scope: LeaderboardReadScope) -> Subquery:
    """scope内で表示可能なUser best Scoreをrank付きで返すsubqueryを構築する.

    Args:
        scope (LeaderboardReadScope): Beatmap,ruleset,playstyle,category filterを含むread scope.

    Returns:
        Subquery: ranked_candidatesという名前で表示fieldとglobal rankを返すsubquery.

    Raises:
        ValueError: SELECTED_MODS categoryでscope.selected_modsがNoneの場合.

    Notes:
        passed,leaderboard eligible,role permission,effective Beatmap statusを同時に満たす
        Scoreだけを含める.
    """
    user_best_score_ids = _user_best_score_ids_subquery(scope)
    role_permissions = _role_permissions_subquery()
    effective_status = _effective_beatmap_status_expression()
    candidate_filters: list[ColumnElement[bool]] = [
        BeatmapModel.id == scope.beatmap_id,
        BeatmapModel.checksum_md5 == scope.beatmap_checksum,
        ScoreModel.beatmap_id == scope.beatmap_id,
        ScoreModel.beatmap_checksum == scope.beatmap_checksum,
        ScoreModel.ruleset == scope.ruleset.value,
        ScoreModel.playstyle == scope.playstyle.value,
        ScoreModel.passed.is_(True),
        ScoreModel.leaderboard_eligible_at_submission.is_(True),
        effective_status.in_(_VISIBLE_BEATMAP_STATUS_VALUES),
        _leaderboard_visible_condition(role_permissions),
    ]
    category_filter = _category_filter_condition(scope)
    if category_filter is not None:
        candidate_filters.append(category_filter)

    replay_exists = (
        select(ReplayModel.id).where(ReplayModel.score_id == ScoreModel.id).limit(1).exists()
    )
    pp = case(
        (
            effective_status.in_(_PP_VISIBLE_BEATMAP_STATUS_VALUES),
            ScorePerformanceCalculationModel.pp,
        ),
        else_=None,
    )
    rank = func.row_number().over(
        order_by=(
            ScoreModel.score.desc(),
            ScoreModel.submitted_at.asc(),
            ScoreModel.id.asc(),
        )
    )

    return (
        select(
            ScoreModel.id.label("score_id"),
            ScoreModel.user_id.label("user_id"),
            UserModel.username.label("username"),
            ScoreModel.beatmap_id.label("beatmap_id"),
            ScoreModel.ruleset.label("ruleset"),
            ScoreModel.playstyle.label("playstyle"),
            ScoreModel.score.label("score"),
            ScoreModel.max_combo.label("max_combo"),
            ScoreModel.n50.label("n50"),
            ScoreModel.n100.label("n100"),
            ScoreModel.n300.label("n300"),
            ScoreModel.miss.label("miss"),
            ScoreModel.katu.label("katu"),
            ScoreModel.geki.label("geki"),
            ScoreModel.perfect.label("perfect"),
            ScoreModel.mods.label("displayed_mods"),
            ScoreModel.submitted_at.label("submitted_at"),
            replay_exists.label("has_replay"),
            pp.label("pp"),
            rank.label("rank"),
        )
        .select_from(user_best_score_ids)
        .join(ScoreModel, ScoreModel.id == user_best_score_ids.c.score_id)
        .join(BeatmapModel, BeatmapModel.id == ScoreModel.beatmap_id)
        .join(UserModel, UserModel.id == ScoreModel.user_id)
        .outerjoin(role_permissions, role_permissions.c.user_id == UserModel.id)
        .outerjoin(
            ScorePerformanceCalculationModel,
            and_(
                ScorePerformanceCalculationModel.score_id == ScoreModel.id,
                ScorePerformanceCalculationModel.is_current.is_(True),
            ),
        )
        .where(*candidate_filters)
        .subquery("ranked_candidates")
    )


def _select_ranked_candidate_rows(
    ranked_candidates: Subquery,
) -> Select[
    tuple[
        int,
        int,
        str,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        bool,
        int,
        int,
        datetime,
        bool,
        Decimal | None,
    ]
]:
    """順位付きcandidate subqueryからdomain row作成に必要なcolumnだけを選択する.

    Args:
        ranked_candidates (Subquery): Score,display field,rankを含むranked candidate subquery.

    Returns:
        Select: BeatmapLeaderboardRowの全fieldに対応するcolumnを返すSELECT statement.

    Notes:
        filteringとorderingは呼び出し側が追加し,このhelperはcolumn projectionだけを所有する.
    """
    return select(
        ranked_candidates.c.score_id,
        ranked_candidates.c.user_id,
        ranked_candidates.c.username,
        ranked_candidates.c.beatmap_id,
        ranked_candidates.c.ruleset,
        ranked_candidates.c.playstyle,
        ranked_candidates.c.score,
        ranked_candidates.c.max_combo,
        ranked_candidates.c.n50,
        ranked_candidates.c.n100,
        ranked_candidates.c.n300,
        ranked_candidates.c.miss,
        ranked_candidates.c.katu,
        ranked_candidates.c.geki,
        ranked_candidates.c.perfect,
        ranked_candidates.c.displayed_mods,
        ranked_candidates.c.rank,
        ranked_candidates.c.submitted_at,
        ranked_candidates.c.has_replay,
        ranked_candidates.c.pp,
    )


def _role_permissions_subquery() -> Subquery:
    """Userごとの集約Role permissionを返すsubqueryを構築する.

    Returns:
        Subquery: user_idと割り当てRole permissionのbitwise ORを返すrole_permissions subquery.

    Notes:
        RoleがないUserのpermission補完は呼び出し側のcoalesceで行う.
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


def _effective_beatmap_status_expression() -> ColumnElement[str]:
    """ローカルoverrideを優先するeffective Beatmap statusのSQL expressionを構築する.

    Returns:
        ColumnElement[str]: local override優先のeffective statusを返すexpression.

    Notes:
        enum columnをStringへcastし,status値の比較をSQL側で一貫させる.
    """
    return cast(
        "ColumnElement[str]",
        func.coalesce(
            sql_cast(BeatmapModel.local_status_override, String),
            sql_cast(BeatmapModel.official_status, String),
        ),
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


def _category_filter_condition(scope: LeaderboardReadScope) -> ColumnElement[bool] | None:
    """Leaderboard categoryに対応する追加SQL filterを返す.

    Args:
        scope (LeaderboardReadScope): categoryとcountry,eligible User IDなどを含むread scope.

    Returns:
        ColumnElement[bool] | None: COUNTRYまたはFRIENDSの追加filter.
        GLOBALなど追加filter不要なcategoryではNone.

    Notes:
        利用不可のcountryまたはfriends scopeはliteral(False)を返し,候補を空にする.
    """
    if scope.category is LeaderboardCategory.COUNTRY:
        country = scope.country
        if not country_leaderboard_is_available(country):
            return literal(False)
        return UserModel.country == country
    if scope.category is LeaderboardCategory.FRIENDS:
        eligible_user_ids = scope.eligible_user_ids
        if eligible_user_ids is None or not friends_leaderboard_is_available(eligible_user_ids):
            return literal(False)
        return UserModel.id.in_(eligible_user_ids)
    return None


def _row_from_mapping(row: object) -> BeatmapLeaderboardRow:
    """SQLAlchemy mapping rowをdomain BeatmapLeaderboardRowへ変換する.

    Args:
        row (object): ranked candidate SELECTから取得したmapping形式のrow.

    Returns:
        BeatmapLeaderboardRow: hit count,mods,rank,replay有無,PPを含むdomain leaderboard row.

    Raises:
        KeyError: mappingに必須fieldがない場合.
        TypeError: mappingの必須field型が期待値と異なる場合.
        ValueError: ruleset,playstyle,またはdisplayed mods bitmaskをdomain valueへ変換
            できない場合.

    Notes:
        PPはDecimalまたはNoneだけを受け入れ,mods bitmaskはModCombinationへ変換する.
    """
    mapping = cast("Mapping[str, object]", row)
    return BeatmapLeaderboardRow(
        score_id=_int_value(mapping, "score_id"),
        user_id=_int_value(mapping, "user_id"),
        username=_str_value(mapping, "username"),
        beatmap_id=_int_value(mapping, "beatmap_id"),
        ruleset=Ruleset(_int_value(mapping, "ruleset")),
        playstyle=Playstyle(_int_value(mapping, "playstyle")),
        score=_int_value(mapping, "score"),
        max_combo=_int_value(mapping, "max_combo"),
        hit_counts=ScoreHitCounts(
            n50=_int_value(mapping, "n50"),
            n100=_int_value(mapping, "n100"),
            n300=_int_value(mapping, "n300"),
            miss=_int_value(mapping, "miss"),
            katu=_int_value(mapping, "katu"),
            geki=_int_value(mapping, "geki"),
        ),
        perfect=_bool_value(mapping, "perfect"),
        displayed_mods=ModCombination.from_persistence_bitmask(
            _int_value(mapping, "displayed_mods")
        ),
        rank=_int_value(mapping, "rank"),
        submitted_at=_datetime_value(mapping, "submitted_at"),
        has_replay=_bool_value(mapping, "has_replay"),
        pp=_decimal_or_none(mapping.get("pp")),
    )


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


def _datetime_value(mapping: Mapping[str, object], key: str) -> datetime:
    """mappingからdatetime型の必須fieldを取得する.

    Args:
        mapping (Mapping[str, object]): SQLAlchemy mapping row.
        key (str): 取得する必須field名.

    Returns:
        datetime: keyに対応するdatetime値.

    Raises:
        KeyError: keyがmappingに存在しない場合.
        TypeError: keyに対応する値がdatetimeではない場合.
    """
    value = mapping[key]
    if not isinstance(value, datetime):
        msg = f"{key} must be a datetime"
        raise TypeError(msg)
    return value


def _decimal_or_none(value: object) -> Decimal | None:
    """PP fieldをDecimalまたはNoneとして検証して返す.

    Args:
        value (object): SQLAlchemy mapping rowから取得したPP field.

    Returns:
        Decimal | None: DecimalのPP値. SQL NULLの場合はNone.

    Raises:
        TypeError: valueがDecimalでもNoneでもない場合.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    msg = "pp must be Decimal or None"
    raise TypeError(msg)


__all__ = ["SQLAlchemyBeatmapLeaderboardQueryRepository"]

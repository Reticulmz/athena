"""SQLAlchemyからcurrent UserStatsのsource dataをread-onlyで取得するquery repositoryを提供する."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import aliased

from osu_server.domain.identity.leaderboard_visibility import (
    LEADERBOARD_VISIBLE_PERMISSION_MASK,
)
from osu_server.domain.scores.mods import Mod
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserPerformanceBest, UserStatsHitTotals
from osu_server.repositories.interfaces.queries.user_stats import (
    UserStatsSourceRead,
    UserStatsSourceRow,
)
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.score import ScoreModel
from osu_server.repositories.sqlalchemy.models.user import UserModel
from osu_server.repositories.sqlalchemy.models.user_stats import (
    BeatmapPerformanceBestModel,
    CurrentUserStatsModel,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.sql.base import Executable
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.selectable import Subquery

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_EXCLUDED_INITIAL_STATS_MODS = int(Mod.RELAX | Mod.AUTOPILOT)


class SQLAlchemyUserStatsQueryRepository:
    """SQLAlchemyからcurrent UserStats source dataをread-onlyで読む.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.
    """

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """短命なread session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Returns:
            None: 読み取り用session factoryを保持したrepository instanceを初期化する.

        Notes:
            初期化時にはsessionを生成せず,current stats projectionとScoreを変更しない.
        """
        self._session_factory: SQLAlchemyQuerySessionFactory = session_factory

    async def read_current_stats_sources(
        self,
        user_ids: tuple[int, ...],
        *,
        ruleset: Ruleset = Ruleset.OSU,
        playstyle: Playstyle = Playstyle.VANILLA,
    ) -> UserStatsSourceRead:
        """重複を除いたrequested Userのcurrent stats source dataをbatchで返す.

        Args:
            user_ids (tuple[int, ...]): 取得対象Userの永続ID. 同じIDは最初の出現だけを使用する.
            ruleset (Ruleset): current statsとfallback Scoreを絞り込むruleset.
            playstyle (Playstyle): current statsとfallback Scoreを絞り込むplaystyle.

        Returns:
            UserStatsSourceRead: 既知Userのsource rowと空のrank_inputsを含むread result.
            空入力または未知Userだけの場合は両fieldが空のresult.

        Raises:
            KeyError: SQL result rowに必須fieldがない場合.
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            TypeError: SQL result rowの必須field型が期待値と異なる場合.

        Notes:
            current projectionがない既知UserだけをScore aggregateとperformance bestからfallbackし,
            空入力ではsessionを開かない.
        """
        ordered_user_ids = tuple(dict.fromkeys(user_ids))
        if len(ordered_user_ids) == 0:
            return UserStatsSourceRead(users=(), rank_inputs=())

        async with self._session_factory() as session:
            known_user_rows = _mapping_rows(
                (await session.execute(_known_user_ids_statement(ordered_user_ids)))
                .mappings()
                .all()
            )
            known_user_ids = _known_user_ids_from_rows(known_user_rows)
            if len(known_user_ids) == 0:
                return UserStatsSourceRead(users=(), rank_inputs=())

            requested_projection_rows = _mapping_rows(
                (
                    await session.execute(
                        _requested_projection_statement(
                            tuple(known_user_ids),
                            ruleset=ruleset,
                            playstyle=playstyle,
                        )
                    )
                )
                .mappings()
                .all()
            )
            requested_projections = _projection_rows_by_user(requested_projection_rows)
            missing_projection_user_ids = tuple(
                user_id for user_id in known_user_ids if user_id not in requested_projections
            )
            if len(missing_projection_user_ids) > 0:
                aggregate_rows = _mapping_rows(
                    (
                        await session.execute(
                            _score_aggregates_statement(
                                missing_projection_user_ids,
                                ruleset=ruleset,
                                playstyle=playstyle,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                requested_best_rows = _mapping_rows(
                    (
                        await session.execute(
                            _requested_bests_statement(
                                missing_projection_user_ids,
                                ruleset=ruleset,
                                playstyle=playstyle,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
            else:
                aggregate_rows = ()
                requested_best_rows = ()
            requested_rank_rows = _mapping_rows(
                (
                    await session.execute(
                        _requested_projection_ranks_statement(
                            tuple(known_user_ids),
                            ruleset=ruleset,
                            playstyle=playstyle,
                        )
                    )
                )
                .mappings()
                .all()
            )

        aggregates = _score_aggregates_by_user(aggregate_rows)
        requested_bests = _best_performances_by_user(requested_best_rows)
        requested_ranks = _global_ranks_by_user(requested_rank_rows)

        return UserStatsSourceRead(
            users=tuple(
                _source_row_for_user(
                    user_id=user_id,
                    projection=requested_projections.get(user_id),
                    aggregate=aggregates.get(user_id),
                    best_performances=requested_bests.get(user_id, ()),
                    global_rank=requested_ranks.get(user_id),
                    ruleset=ruleset,
                    playstyle=playstyle,
                )
                for user_id in ordered_user_ids
                if user_id in known_user_ids
            ),
            rank_inputs=(),
        )


def _known_user_ids_statement(user_ids: tuple[int, ...]) -> Executable:
    """入力IDのうちUser tableに存在するIDを取得するstatementを構築する.

    Args:
        user_ids (tuple[int, ...]): 存在確認するUserの永続ID.

    Returns:
        Executable: user_id columnを返すSELECT statement.

    Notes:
        入力順の保持や重複除去は呼び出し側が所有する.
    """
    return select(UserModel.id.label("user_id")).where(UserModel.id.in_(user_ids))


def _score_aggregates_statement(
    user_ids: tuple[int, ...],
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> Executable:
    """Current projectionがないUser向けのScore aggregateを取得するstatementを構築する.

    Args:
        user_ids (tuple[int, ...]): aggregateを計算するUserの永続ID.
        ruleset (Ruleset): Scoreを絞り込むruleset.
        playstyle (Playstyle): Scoreを絞り込むplaystyle.

    Returns:
        Executable: play count,score,combo,play time,hit totalをUser別に返すSELECT statement.

    Notes:
        ranked scoreはpassedかつleaderboard eligibleなScoreのBeatmap別最高値だけを合計し,
        initial statsからRELAXとAUTOPILOT modを除外する.
    """
    ranked_score_model = aliased(ScoreModel)
    ranked_score_candidates = (
        select(
            ranked_score_model.user_id.label("user_id"),
            ranked_score_model.beatmap_id.label("beatmap_id"),
            func.max(ranked_score_model.score).label("score"),
        )
        .where(
            ranked_score_model.user_id.in_(user_ids),
            ranked_score_model.ruleset == ruleset.value,
            ranked_score_model.playstyle == playstyle.value,
            ranked_score_model.passed.is_(True),
            ranked_score_model.leaderboard_eligible_at_submission.is_(True),
            (ranked_score_model.mods.op("&")(_EXCLUDED_INITIAL_STATS_MODS)) == 0,
        )
        .group_by(ranked_score_model.user_id, ranked_score_model.beatmap_id)
        .subquery("ranked_score_candidates")
    )
    ranked_scores = (
        select(
            ranked_score_candidates.c.user_id.label("user_id"),
            func.coalesce(func.sum(ranked_score_candidates.c.score), 0).label("ranked_score"),
        )
        .group_by(ranked_score_candidates.c.user_id)
        .subquery("ranked_scores")
    )
    return (
        select(
            ScoreModel.user_id.label("user_id"),
            func.count(ScoreModel.id).label("play_count"),
            func.coalesce(ranked_scores.c.ranked_score, 0).label("ranked_score"),
            func.coalesce(func.sum(ScoreModel.score), 0).label("total_score"),
            func.coalesce(func.max(ScoreModel.max_combo), 0).label("max_combo"),
            func.sum(ScoreModel.play_time_seconds).label("play_time_seconds"),
            func.coalesce(func.sum(ScoreModel.n300), 0).label("count_300"),
            func.coalesce(func.sum(ScoreModel.n100), 0).label("count_100"),
            func.coalesce(func.sum(ScoreModel.n50), 0).label("count_50"),
            func.coalesce(func.sum(ScoreModel.geki), 0).label("count_geki"),
            func.coalesce(func.sum(ScoreModel.katu), 0).label("count_katu"),
            func.coalesce(func.sum(ScoreModel.miss), 0).label("count_miss"),
        )
        .where(
            ScoreModel.user_id.in_(user_ids),
            ScoreModel.ruleset == ruleset.value,
            ScoreModel.playstyle == playstyle.value,
            _initial_stats_mod_condition(),
        )
        .outerjoin(ranked_scores, ranked_scores.c.user_id == ScoreModel.user_id)
        .group_by(ScoreModel.user_id, ranked_scores.c.ranked_score)
    )


def _requested_projection_statement(
    user_ids: tuple[int, ...],
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> Executable:
    """指定Userのcurrent stats projectionを取得するstatementを構築する.

    Args:
        user_ids (tuple[int, ...]): projectionを検索するUserの永続ID.
        ruleset (Ruleset): projectionを絞り込むruleset.
        playstyle (Playstyle): projectionを絞り込むplaystyle.

    Returns:
        Executable: current stats projectionの全source fieldを返すSELECT statement.

    Notes:
        projectionが存在しないUserのfallback計算はこのstatementでは行わない.
    """
    return _projection_rows_select().where(
        CurrentUserStatsModel.user_id.in_(user_ids),
        CurrentUserStatsModel.ruleset == ruleset.value,
        CurrentUserStatsModel.playstyle == playstyle.value,
    )


def _requested_bests_statement(
    user_ids: tuple[int, ...],
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> Executable:
    """指定Userのperformance bestを順位決定順で取得するstatementを構築する.

    Args:
        user_ids (tuple[int, ...]): performance bestを検索するUserの永続ID.
        ruleset (Ruleset): performance bestを絞り込むruleset.
        playstyle (Playstyle): performance bestを絞り込むplaystyle.

    Returns:
        Executable: User別performance bestのPPとaccuracyを返すSELECT statement.

    Notes:
        同一User内ではPP降順,submitted_at昇順,Score ID昇順で並べる.
    """
    return (
        _best_rows_select()
        .where(
            BeatmapPerformanceBestModel.user_id.in_(user_ids),
            BeatmapPerformanceBestModel.ruleset == ruleset.value,
            BeatmapPerformanceBestModel.playstyle == playstyle.value,
        )
        .order_by(
            BeatmapPerformanceBestModel.user_id.asc(),
            BeatmapPerformanceBestModel.pp.desc(),
            BeatmapPerformanceBestModel.submitted_at.asc(),
            BeatmapPerformanceBestModel.score_id.asc(),
        )
    )


def _requested_projection_ranks_statement(
    user_ids: tuple[int, ...],
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> Executable:
    """指定Userのvisible global rankを取得するstatementを構築する.

    Args:
        user_ids (tuple[int, ...]): rankを計算するUserの永続ID.
        ruleset (Ruleset): current stats projectionを絞り込むruleset.
        playstyle (Playstyle): current stats projectionを絞り込むplaystyle.

    Returns:
        Executable: visibleなnonzero PPのUser別global rankを返すSELECT statement.

    Notes:
        同PP時はUser IDが小さい方を上位とし,targetと比較対象の両方へRole visibilityを適用する.
    """
    target = aliased(CurrentUserStatsModel)
    better = aliased(CurrentUserStatsModel)
    target_role_permissions = _role_permissions_subquery("target_role_permissions")
    better_role_permissions = _role_permissions_subquery("better_role_permissions")
    visible_better = case(
        (
            _leaderboard_visible_condition(better_role_permissions),
            better.user_id,
        )
    )
    return (
        select(
            target.user_id.label("user_id"),
            (func.count(visible_better) + literal(1)).label("global_rank"),
        )
        .select_from(target)
        .join(UserModel, UserModel.id == target.user_id)
        .outerjoin(
            target_role_permissions,
            target_role_permissions.c.user_id == target.user_id,
        )
        .outerjoin(
            better,
            and_(
                better.ruleset == target.ruleset,
                better.playstyle == target.playstyle,
                better.pp > literal(0),
                or_(
                    better.pp > target.pp,
                    and_(better.pp == target.pp, better.user_id < target.user_id),
                ),
            ),
        )
        .outerjoin(
            better_role_permissions,
            better_role_permissions.c.user_id == better.user_id,
        )
        .where(
            target.user_id.in_(user_ids),
            target.ruleset == ruleset.value,
            target.playstyle == playstyle.value,
            target.pp > literal(0),
            _leaderboard_visible_condition(target_role_permissions),
        )
        .group_by(
            target.user_id,
            target.pp,
        )
        .order_by(target.user_id.asc())
    )


def _projection_rows_select():
    """Current stats projectionをdomain source rowへ変換する全columnのSELECTを構築する.

    Returns:
        Select: User ID,PP,accuracy,Score aggregate,hit totalを返すSELECT statement.

    Notes:
        filteringは呼び出し側が追加し,このhelperはcolumn projectionだけを所有する.
    """
    return select(
        CurrentUserStatsModel.user_id.label("user_id"),
        CurrentUserStatsModel.pp.label("pp"),
        CurrentUserStatsModel.accuracy.label("accuracy"),
        CurrentUserStatsModel.play_count.label("play_count"),
        CurrentUserStatsModel.ranked_score.label("ranked_score"),
        CurrentUserStatsModel.total_score.label("total_score"),
        CurrentUserStatsModel.max_combo.label("max_combo"),
        CurrentUserStatsModel.play_time_seconds.label("play_time_seconds"),
        CurrentUserStatsModel.count_300.label("count_300"),
        CurrentUserStatsModel.count_100.label("count_100"),
        CurrentUserStatsModel.count_50.label("count_50"),
        CurrentUserStatsModel.count_geki.label("count_geki"),
        CurrentUserStatsModel.count_katu.label("count_katu"),
        CurrentUserStatsModel.count_miss.label("count_miss"),
    )


def _best_rows_select():
    """Performance bestをdomain valueへ変換する最小columnのSELECTを構築する.

    Returns:
        Select: User ID,PP,accuracyを返すSELECT statement.

    Notes:
        filteringとorderingは呼び出し側が追加する.
    """
    return select(
        BeatmapPerformanceBestModel.user_id.label("user_id"),
        BeatmapPerformanceBestModel.pp.label("pp"),
        BeatmapPerformanceBestModel.accuracy.label("accuracy"),
    )


def _role_permissions_subquery(name: str = "role_permissions") -> Subquery:
    """Userごとの集約Role permissionを返す名前付きsubqueryを構築する.

    Args:
        name (str): generated subqueryに付与するSQL alias名.

    Returns:
        Subquery: user_idと割り当てRole permissionのbitwise ORを返すsubquery.

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
        .subquery(name)
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


def _initial_stats_mod_condition() -> ColumnElement[bool]:
    """初期stats aggregateからRELAXとAUTOPILOTを除外するSQL条件を構築する.

    Returns:
        ColumnElement[bool]: excluded mod bitが1つも立っていないScoreだけを許可するSQL条件.

    Notes:
        除外bitmaskはMod.RELAXとMod.AUTOPILOTのORとしてmodule定数に固定する.
    """
    return ScoreModel.mods.bitwise_and(_EXCLUDED_INITIAL_STATS_MODS) == literal(0)


def _known_user_ids_from_rows(rows: tuple[Mapping[str, object], ...]) -> set[int]:
    """既知User queryのmapping rowからUser ID集合を作る.

    Args:
        rows (tuple[Mapping[str, object], ...]): user_id fieldを持つSQLAlchemy mapping row.

    Returns:
        set[int]: rowに含まれるUser IDの重複なし集合.

    Raises:
        KeyError: mappingにuser_idがない場合.
        TypeError: user_idがintではない場合.
    """
    return {_int_value(row, "user_id") for row in rows}


def _score_aggregates_by_user(
    rows: tuple[Mapping[str, object], ...],
) -> dict[int, Mapping[str, object]]:
    """Score aggregate rowをUser IDで索引付けする.

    Args:
        rows (tuple[Mapping[str, object], ...]): user_idを含むScore aggregateのmapping row.

    Returns:
        dict[int, Mapping[str, object]]: User IDをkeyとする最後のaggregate row.

    Raises:
        KeyError: mappingにuser_idがない場合.
        TypeError: user_idがintではない場合.

    Notes:
        同じUser IDが複数ある場合は後ろのrowで上書きする.
    """
    return {_int_value(row, "user_id"): row for row in rows}


def _projection_rows_by_user(
    rows: tuple[Mapping[str, object], ...],
) -> dict[int, Mapping[str, object]]:
    """Current stats projection rowをUser IDで索引付けする.

    Args:
        rows (tuple[Mapping[str, object], ...]): user_idを含むprojectionのmapping row.

    Returns:
        dict[int, Mapping[str, object]]: User IDをkeyとする最後のprojection row.

    Raises:
        KeyError: mappingにuser_idがない場合.
        TypeError: user_idがintではない場合.

    Notes:
        同じUser IDが複数ある場合は後ろのrowで上書きする.
    """
    return {_int_value(row, "user_id"): row for row in rows}


def _global_ranks_by_user(rows: tuple[Mapping[str, object], ...]) -> dict[int, int]:
    """Global rank rowをUser IDからrankへのmappingへ変換する.

    Args:
        rows (tuple[Mapping[str, object], ...]): user_idとglobal_rankを含むmapping row.

    Returns:
        dict[int, int]: User IDをkey,global rankをvalueとするmapping.

    Raises:
        KeyError: mappingにuser_idまたはglobal_rankがない場合.
        TypeError: user_idまたはglobal_rankがintではない場合.
    """
    return {_int_value(row, "user_id"): _int_value(row, "global_rank") for row in rows}


def _best_performances_by_user(
    rows: tuple[Mapping[str, object], ...],
) -> dict[int, tuple[UserPerformanceBest, ...]]:
    """Performance best rowをUser ID別のdomain tupleへ変換する.

    Args:
        rows (tuple[Mapping[str, object], ...]): user_id,PP,accuracyを含むmapping row.

    Returns:
        dict[int, tuple[UserPerformanceBest, ...]]: User IDごとの入力順performance best tuple.

    Raises:
        KeyError: mappingにuser_id,pp,accuracyがない場合.
        TypeError: user_id,PP,accuracyの型が期待値と異なる場合.
    """
    grouped: dict[int, list[UserPerformanceBest]] = defaultdict(list)
    for row in rows:
        grouped[_int_value(row, "user_id")].append(
            UserPerformanceBest(
                pp=_decimal_value(row, "pp"),
                accuracy=_float_value(row, "accuracy"),
            )
        )
    return {user_id: tuple(bests) for user_id, bests in grouped.items()}


def _source_row_for_user(
    *,
    user_id: int,
    projection: Mapping[str, object] | None,
    aggregate: Mapping[str, object] | None,
    best_performances: tuple[UserPerformanceBest, ...],
    global_rank: int | None,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> UserStatsSourceRow:
    """1人分のprojectionまたはfallback aggregateをUserStats source rowへ変換する.

    Args:
        user_id (int): 変換対象Userの永続ID.
        projection (Mapping[str, object] | None): current stats projection row. 未作成時はNone.
        aggregate (Mapping[str, object] | None): projection未作成時のScore aggregate row.
            未作成時はNone.
        best_performances (tuple[UserPerformanceBest, ...]): projection未作成時に使う
            performance best.
        global_rank (int | None): visible global rank. rank対象外または未取得時はNone.
        ruleset (Ruleset): rowに記録するruleset scope.
        playstyle (Playstyle): rowに記録するplaystyle scope.

    Returns:
        UserStatsSourceRow: projection優先,aggregate fallback,またはzero値で構成したsource row.

    Raises:
        KeyError: 使用したmappingに必須fieldがない場合.
        TypeError: 使用したmappingの必須field型が期待値と異なる場合.

    Notes:
        projectionがある場合はbest_performancesを空tupleにし,aggregateもない既知Userはzero値を返す.
    """
    if projection is not None:
        return UserStatsSourceRow(
            user_id=user_id,
            play_count=_int_value(projection, "play_count"),
            ranked_score=_int_value(projection, "ranked_score"),
            total_score=_int_value(projection, "total_score"),
            max_combo=_int_value(projection, "max_combo"),
            play_time_seconds=_optional_int_value(projection, "play_time_seconds"),
            best_performances=(),
            ruleset=ruleset,
            playstyle=playstyle,
            hit_totals=_hit_totals_from_row(projection),
            pp=_decimal_value(projection, "pp"),
            accuracy=_float_value(projection, "accuracy"),
            global_rank=global_rank,
        )

    if aggregate is None:
        return UserStatsSourceRow(
            user_id=user_id,
            play_count=0,
            ranked_score=0,
            total_score=0,
            max_combo=0,
            play_time_seconds=None,
            best_performances=best_performances,
            ruleset=ruleset,
            playstyle=playstyle,
        )
    return UserStatsSourceRow(
        user_id=user_id,
        play_count=_int_value(aggregate, "play_count"),
        ranked_score=_int_value(aggregate, "ranked_score"),
        total_score=_int_value(aggregate, "total_score"),
        max_combo=_int_value(aggregate, "max_combo"),
        play_time_seconds=_optional_int_value(aggregate, "play_time_seconds"),
        best_performances=best_performances,
        ruleset=ruleset,
        playstyle=playstyle,
        hit_totals=_hit_totals_from_row(aggregate),
    )


def _hit_totals_from_row(row: Mapping[str, object]) -> UserStatsHitTotals:
    """SQL mapping rowのhit count fieldをdomain UserStatsHitTotalsへ変換する.

    Args:
        row (Mapping[str, object]): count_300,count_100,count_50,count_geki,count_katu,
            count_missを持つrow.

    Returns:
        UserStatsHitTotals: 各hit countを転記したdomain value.

    Raises:
        KeyError: mappingに必須hit count fieldがない場合.
        TypeError: 必須hit count fieldがintではない場合.
    """
    return UserStatsHitTotals(
        count_300=_int_value(row, "count_300"),
        count_100=_int_value(row, "count_100"),
        count_50=_int_value(row, "count_50"),
        count_geki=_int_value(row, "count_geki"),
        count_katu=_int_value(row, "count_katu"),
        count_miss=_int_value(row, "count_miss"),
    )


def _mapping_rows(rows: object) -> tuple[Mapping[str, object], ...]:
    """SQLAlchemy result row listをmapping row tupleとして扱う.

    Args:
        rows (object): mappings().all()から取得したrow list.

    Returns:
        tuple[Mapping[str, object], ...]: 入力順を保持したmapping row tuple.

    Notes:
        runtime validationは行わず,呼び出し側がmapping形式のresultを渡す契約に依存する.
    """
    return tuple(cast("Mapping[str, object]", row) for row in cast("list[object]", rows))


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


def _optional_int_value(mapping: Mapping[str, object], key: str) -> int | None:
    """mappingからintまたはNoneの必須fieldを取得する.

    Args:
        mapping (Mapping[str, object]): SQLAlchemy mapping row.
        key (str): 取得する必須field名.

    Returns:
        int | None: keyに対応するint値. SQL NULLの場合はNone.

    Raises:
        KeyError: keyがmappingに存在しない場合.
        TypeError: keyに対応する値がintでもNoneでもない場合.
    """
    value = mapping[key]
    if value is None:
        return None
    if isinstance(value, int):
        return value
    msg = f"{key} must be an int or None"
    raise TypeError(msg)


def _decimal_value(mapping: Mapping[str, object], key: str) -> Decimal:
    """mappingからDecimal型の必須fieldを取得する.

    Args:
        mapping (Mapping[str, object]): SQLAlchemy mapping row.
        key (str): 取得する必須field名.

    Returns:
        Decimal: keyに対応するDecimal値.

    Raises:
        KeyError: keyがmappingに存在しない場合.
        TypeError: keyに対応する値がDecimalではない場合.
    """
    value = mapping[key]
    if isinstance(value, Decimal):
        return value
    msg = f"{key} must be Decimal"
    raise TypeError(msg)


def _float_value(mapping: Mapping[str, object], key: str) -> float:
    """mappingからfloat型の必須fieldを取得する.

    Args:
        mapping (Mapping[str, object]): SQLAlchemy mapping row.
        key (str): 取得する必須field名.

    Returns:
        float: keyに対応するfloat値.

    Raises:
        KeyError: keyがmappingに存在しない場合.
        TypeError: keyに対応する値がfloatではない場合.
    """
    value = mapping[key]
    if isinstance(value, float):
        return value
    msg = f"{key} must be a float"
    raise TypeError(msg)


__all__ = ["SQLAlchemyUserStatsQueryRepository"]

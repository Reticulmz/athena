"""SQLAlchemy query-side Beatmap Leaderboard repository."""

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
from osu_server.domain.scores.leaderboards import NO_MOD_FILTER_KEY
from osu_server.domain.scores.mods import Mod, ModCombination
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
    from sqlalchemy.sql.selectable import Subquery

    from osu_server.repositories.sqlalchemy.queries._shared import SQLAlchemyQuerySessionFactory

_MAX_QUERY_LIMIT = 50
_NIGHTCORE_BIT = int(Mod.NIGHTCORE)
_DOUBLE_TIME_BIT = int(Mod.DOUBLE_TIME)
_PERFECT_BIT = int(Mod.PERFECT)
_SUDDEN_DEATH_BIT = int(Mod.SUDDEN_DEATH)
_MIRROR_BIT = int(Mod.MIRROR)
_PREFERENCE_ONLY_NO_MODS_BITS = int(Mod.SUDDEN_DEATH | Mod.PERFECT | Mod.MIRROR)
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
    """source scores から Beatmap Leaderboard を構築する query repository.

    Notes:
        read-only の short session を使い、projection table を参照または更新しない.
    """

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        self._session_factory: SQLAlchemyQuerySessionFactory = session_factory

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        """指定 scope の上位行を deterministic な順位で返す.

        Args:
            scope (LeaderboardReadScope): Beatmapとcategory filterを含むscope.
            limit (int): 取得上限. repository上限を超える値は切り詰める.

        Returns:
            tuple[BeatmapLeaderboardRow, ...]: User別最高scoreの順位付き行.
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
        """Viewer の Personal Best と全体順位を返す.

        Args:
            scope (LeaderboardReadScope): Beatmapとcategory filterを含むscope.
            viewer_user_id (int): Personal Bestを取得するUser ID.

        Returns:
            BeatmapLeaderboardRow | None: 対象scoreの順位付き行またはNone.
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
        async with self._session_factory() as session:
            result = await session.execute(statement)
            rows = result.mappings().all()
        return tuple(_row_from_mapping(cast("object", row)) for row in rows)


def _user_best_score_ids_subquery(scope: LeaderboardReadScope) -> Subquery:
    candidate_filters: list[ColumnElement[bool]] = [
        ScoreModel.beatmap_id == scope.beatmap_id,
        ScoreModel.beatmap_checksum == scope.beatmap_checksum,
        ScoreModel.ruleset == scope.ruleset.value,
        ScoreModel.playstyle == scope.playstyle.value,
        ScoreModel.passed.is_(True),
        ScoreModel.leaderboard_eligible_at_submission.is_(True),
    ]
    selected_mod_filter = _selected_mod_filter_condition(scope)
    if selected_mod_filter is not None:
        candidate_filters.append(selected_mod_filter)

    user_rank = func.row_number().over(
        partition_by=ScoreModel.user_id,
        order_by=(
            ScoreModel.score.desc(),
            ScoreModel.submitted_at.asc(),
            ScoreModel.id.asc(),
        ),
    )
    ranked_user_scores = (
        select(
            ScoreModel.id.label("score_id"),
            user_rank.label("user_rank"),
        )
        .where(*candidate_filters)
        .subquery("ranked_user_scores")
    )
    return (
        select(ranked_user_scores.c.score_id)
        .where(ranked_user_scores.c.user_rank == 1)
        .subquery("user_best_score_ids")
    )


def _ranked_candidates_subquery(scope: LeaderboardReadScope) -> Subquery:
    user_best_score_ids = _user_best_score_ids_subquery(scope)
    role_permissions = _role_permissions_subquery()
    effective_status = _effective_beatmap_status_expression()
    candidate_filters: list[ColumnElement[bool]] = [
        BeatmapModel.id == scope.beatmap_id,
        BeatmapModel.checksum_md5 == scope.beatmap_checksum,
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


def _select_ranked_candidate_rows(ranked_candidates: Subquery):
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
    return cast(
        "ColumnElement[str]",
        func.coalesce(
            sql_cast(BeatmapModel.local_status_override, String),
            sql_cast(BeatmapModel.official_status, String),
        ),
    )


def _leaderboard_visible_condition(role_permissions: Subquery) -> ColumnElement[bool]:
    permissions = cast(
        "ColumnElement[int]",
        func.coalesce(role_permissions.c.permissions, 0),
    )
    return permissions.bitwise_and(LEADERBOARD_VISIBLE_PERMISSION_MASK) == literal(
        LEADERBOARD_VISIBLE_PERMISSION_MASK
    )


def _selected_mod_filter_condition(
    scope: LeaderboardReadScope,
) -> ColumnElement[bool] | None:
    if scope.category is not LeaderboardCategory.SELECTED_MODS:
        return None
    filter_key = scope.mod_filter_key
    if filter_key is None:
        msg = "selected-mods scope requires mod_filter_key"
        raise ValueError(msg)
    canonical_mods = _canonical_mods_expression(
        cast("ColumnElement[int]", cast("object", ScoreModel.mods))
    )
    if filter_key == NO_MOD_FILTER_KEY:
        return canonical_mods.bitwise_and(~_PREFERENCE_ONLY_NO_MODS_BITS) == 0
    return canonical_mods == filter_key


def _canonical_mods_expression(mods: ColumnElement[int]) -> ColumnElement[int]:
    nightcore_normalized = case(
        (
            mods.bitwise_and(_NIGHTCORE_BIT) != 0,
            mods.bitwise_or(_DOUBLE_TIME_BIT).bitwise_and(~_NIGHTCORE_BIT),
        ),
        else_=mods,
    )
    perfect_normalized = case(
        (
            nightcore_normalized.bitwise_and(_PERFECT_BIT) != 0,
            nightcore_normalized.bitwise_or(_SUDDEN_DEATH_BIT).bitwise_and(~_PERFECT_BIT),
        ),
        else_=nightcore_normalized,
    )
    return perfect_normalized.bitwise_and(~_MIRROR_BIT)


def _category_filter_condition(scope: LeaderboardReadScope) -> ColumnElement[bool] | None:
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


def _bool_value(mapping: Mapping[str, object], key: str) -> bool:
    value = mapping[key]
    if not isinstance(value, bool):
        msg = f"{key} must be a bool"
        raise TypeError(msg)
    return value


def _datetime_value(mapping: Mapping[str, object], key: str) -> datetime:
    value = mapping[key]
    if not isinstance(value, datetime):
        msg = f"{key} must be a datetime"
        raise TypeError(msg)
    return value


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    msg = "pp must be Decimal or None"
    raise TypeError(msg)


__all__ = ["SQLAlchemyBeatmapLeaderboardQueryRepository"]

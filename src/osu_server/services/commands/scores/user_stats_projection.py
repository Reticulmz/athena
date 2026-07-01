"""Current UserStats projection rebuild helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.scores.mods import Mod
from osu_server.domain.scores.user_stats import (
    UserPerformanceBest,
    UserStatsHitTotals,
    UserStatsPolicy,
    UserStatsProjection,
    UserStatsScope,
    calculate_ranked_score_from_scores,
)

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Playstyle, Ruleset, Score
    from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
        BeatmapPerformanceBest,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork


async def replace_current_user_stats_projection(
    uow: UnitOfWork,
    *,
    user_id: int,
    ruleset: Ruleset,
    playstyle: Playstyle,
    policy: UserStatsPolicy,
) -> UserStatsProjection:
    """Unit of Work 内で 1 user/mode の current UserStats projection を置き換える。

    Args:
        uow: 呼び出し側が所有する command Unit of Work。
        user_id: 置き換え対象の user id。
        ruleset: 置き換え対象の ruleset。
        playstyle: 置き換え対象の playstyle。
        policy: PP と accuracy の計算 policy。

    Returns:
        永続化された current UserStats projection。

    制約:
        commit は呼び出し側が行う。同一 transaction で score/performance 更新と
        projection 置き換えをまとめたい workflow から使う。
    """
    scope = UserStatsScope(user_id=user_id, ruleset=ruleset, playstyle=playstyle)
    await uow.current_user_stats.lock_scope(scope)
    scores = await uow.scores.list_current_stats_scores_for_user(
        user_id,
        ruleset=ruleset,
        playstyle=playstyle,
    )
    bests = await uow.beatmap_performance_bests.list_user_bests(
        user_id=user_id,
        ruleset=ruleset,
        playstyle=playstyle,
    )
    projection = build_current_user_stats_projection(
        user_id=user_id,
        ruleset=ruleset,
        playstyle=playstyle,
        scores=scores,
        bests=bests,
        policy=policy,
    )
    return await uow.current_user_stats.replace(projection)


def build_current_user_stats_projection(
    *,
    user_id: int,
    ruleset: Ruleset,
    playstyle: Playstyle,
    scores: tuple[Score, ...],
    bests: tuple[BeatmapPerformanceBest, ...],
    policy: UserStatsPolicy,
) -> UserStatsProjection:
    """source scores と performance best rows から current UserStats projection を作る。"""
    scoped_scores = tuple(
        score
        for score in scores
        if score.user_id == user_id
        and score.ruleset is ruleset
        and score.playstyle is playstyle
        and _score_in_current_stats_scope(score)
    )
    hit_totals = _hit_totals(scoped_scores)
    performance_totals = policy.calculate_performance_totals(
        tuple(UserPerformanceBest(pp=best.pp, accuracy=best.accuracy) for best in bests)
    )
    play_time_values = tuple(
        score.play_time_seconds for score in scoped_scores if score.play_time_seconds is not None
    )
    return UserStatsProjection(
        scope=UserStatsScope(user_id=user_id, ruleset=ruleset, playstyle=playstyle),
        pp=performance_totals.total_pp,
        accuracy=performance_totals.accuracy,
        play_count=len(scoped_scores),
        ranked_score=calculate_ranked_score_from_scores(scoped_scores),
        total_score=sum(score.score for score in scoped_scores),
        max_combo=max((score.max_combo for score in scoped_scores), default=0),
        play_time_seconds=sum(play_time_values) if len(play_time_values) > 0 else None,
        hit_totals=hit_totals,
    )


def _hit_totals(scores: tuple[Score, ...]) -> UserStatsHitTotals:
    return UserStatsHitTotals(
        count_300=sum(score.n300 for score in scores),
        count_100=sum(score.n100 for score in scores),
        count_50=sum(score.n50 for score in scores),
        count_geki=sum(score.geki for score in scores),
        count_katu=sum(score.katu for score in scores),
        count_miss=sum(score.miss for score in scores),
    )


def _score_in_current_stats_scope(score: Score) -> bool:
    return not score.mods.has(Mod.RELAX) and not score.mods.has(Mod.AUTOPILOT)


__all__ = (
    "build_current_user_stats_projection",
    "replace_current_user_stats_projection",
)

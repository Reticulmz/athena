"""In-memory current UserStats query repository。"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.domain.scores.mods import Mod
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import (
    UserPerformanceBest,
    UserStatsHitTotals,
    UserStatsProjection,
    calculate_ranked_score_from_scores,
)
from osu_server.repositories.interfaces.queries.user_stats import (
    UserStatsRankInput,
    UserStatsSourceRead,
    UserStatsSourceRow,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.scores import Score
    from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
        BeatmapPerformanceBest,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryUserStatsQueryRepository:
    """In-memory state から current UserStats source data を読む。"""

    def __init__(self, factory: InMemoryUnitOfWorkFactory) -> None:
        """共有 in-memory state factory を受け取る。"""
        self._factory: InMemoryUnitOfWorkFactory = factory

    async def read_current_stats_sources(
        self,
        user_ids: tuple[int, ...],
        *,
        ruleset: Ruleset = Ruleset.OSU,
        playstyle: Playstyle = Playstyle.VANILLA,
    ) -> UserStatsSourceRead:
        """dedupe 済み requested users と mode-scoped rank inputs を返す。"""
        state = self._factory.snapshot()
        ordered_user_ids = tuple(dict.fromkeys(user_ids))
        existing_user_ids = tuple(
            user_id for user_id in ordered_user_ids if user_id in state.users_by_id
        )
        bests_by_user = _best_performances_by_user(
            state.beatmap_performance_bests_by_id.values(),
            ruleset=ruleset,
            playstyle=playstyle,
        )
        projections_by_user = _current_stats_projections_by_user(
            state.current_user_stats_by_scope.values(),
            ruleset=ruleset,
            playstyle=playstyle,
        )
        source_rows = tuple(
            _source_row_for_user(
                state=state,
                user_id=user_id,
                ruleset=ruleset,
                playstyle=playstyle,
                projection=projections_by_user.get(user_id),
                best_performances=bests_by_user.get(user_id, ()),
            )
            for user_id in existing_user_ids
        )
        projection_rank_inputs = tuple(
            UserStatsRankInput(user_id=user_id, pp=projection.pp)
            for user_id, projection in sorted(projections_by_user.items())
            if user_id in state.users_by_id and _user_is_leaderboard_visible(state, user_id)
        )
        best_rank_inputs = tuple(
            UserStatsRankInput(
                user_id=user_id,
                best_performances=bests,
            )
            for user_id, bests in sorted(bests_by_user.items())
            if user_id in state.users_by_id
            and user_id not in projections_by_user
            and len(bests) > 0
            and _user_is_leaderboard_visible(state, user_id)
        )
        return UserStatsSourceRead(
            users=source_rows,
            rank_inputs=projection_rank_inputs + best_rank_inputs,
        )


def _source_row_for_user(
    *,
    state: InMemoryCommandRepositoryState,
    user_id: int,
    ruleset: Ruleset,
    playstyle: Playstyle,
    projection: UserStatsProjection | None,
    best_performances: tuple[UserPerformanceBest, ...],
) -> UserStatsSourceRow:
    if projection is not None:
        return UserStatsSourceRow(
            user_id=user_id,
            play_count=projection.play_count,
            ranked_score=projection.ranked_score,
            total_score=projection.total_score,
            max_combo=projection.max_combo,
            play_time_seconds=projection.play_time_seconds,
            best_performances=(),
            ruleset=ruleset,
            playstyle=playstyle,
            hit_totals=projection.hit_totals,
            pp=projection.pp,
            accuracy=projection.accuracy,
        )

    scores = tuple(
        score
        for score in state.scores_by_id.values()
        if score.user_id == user_id
        and _score_in_initial_stats_scope(score, ruleset=ruleset, playstyle=playstyle)
    )
    play_time_values = tuple(
        score.play_time_seconds for score in scores if score.play_time_seconds is not None
    )
    return UserStatsSourceRow(
        user_id=user_id,
        play_count=len(scores),
        ranked_score=calculate_ranked_score_from_scores(scores),
        total_score=sum(score.score for score in scores),
        max_combo=max((score.max_combo for score in scores), default=0),
        play_time_seconds=sum(play_time_values) if len(play_time_values) > 0 else None,
        best_performances=best_performances,
        ruleset=ruleset,
        playstyle=playstyle,
        hit_totals=_hit_totals(scores),
    )


def _score_in_initial_stats_scope(
    score: Score,
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> bool:
    return (
        score.ruleset is ruleset
        and score.playstyle is playstyle
        and not score.mods.has(Mod.RELAX)
        and not score.mods.has(Mod.AUTOPILOT)
    )


def _best_performances_by_user(
    rows: Iterable[BeatmapPerformanceBest],
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> dict[int, tuple[UserPerformanceBest, ...]]:
    grouped: dict[int, list[UserPerformanceBest]] = defaultdict(list)
    for row in rows:
        if row.scope.ruleset is not ruleset or row.scope.playstyle is not playstyle:
            continue
        grouped[row.scope.user_id].append(UserPerformanceBest(pp=row.pp, accuracy=row.accuracy))
    return {
        user_id: tuple(
            sorted(
                bests,
                key=lambda best: best.pp,
                reverse=True,
            )
        )
        for user_id, bests in grouped.items()
    }


def _current_stats_projections_by_user(
    rows: Iterable[UserStatsProjection],
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> dict[int, UserStatsProjection]:
    return {
        row.scope.user_id: row
        for row in rows
        if row.scope.ruleset is ruleset and row.scope.playstyle is playstyle
    }


def _hit_totals(scores: tuple[Score, ...]) -> UserStatsHitTotals:
    return UserStatsHitTotals(
        count_300=sum(score.n300 for score in scores),
        count_100=sum(score.n100 for score in scores),
        count_50=sum(score.n50 for score in scores),
        count_geki=sum(score.geki for score in scores),
        count_katu=sum(score.katu for score in scores),
        count_miss=sum(score.miss for score in scores),
    )


def _user_is_leaderboard_visible(
    state: InMemoryCommandRepositoryState,
    user_id: int,
) -> bool:
    privileges = Privileges.NONE
    for role_id in state.role_ids_by_user_id.get(user_id, set()):
        role = state.roles_by_id.get(role_id)
        if role is not None:
            privileges |= role.permissions
    return is_leaderboard_visible_user(privileges)


__all__ = ("InMemoryUserStatsQueryRepository",)

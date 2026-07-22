"""Committed in-memory state から current UserStats source を読む adapter を提供する."""

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
    """Committed in-memory state から current UserStats source data を読む repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        read model の生成に projection, Score, performance best を使用するが, state を変更しない.
    """

    def __init__(self, factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.

        Returns:
            None: factory を保持する repository を構築する.
        """
        self._factory: InMemoryUnitOfWorkFactory = factory

    async def read_current_stats_sources(
        self,
        user_ids: tuple[int, ...],
        *,
        ruleset: Ruleset = Ruleset.OSU,
        playstyle: Playstyle = Playstyle.VANILLA,
    ) -> UserStatsSourceRead:
        """Requested User の current stats source と mode-scoped rank input を返す.

        Args:
            user_ids (tuple[int, ...]): source を読む User IDs. 重複を含められる.
            ruleset (Ruleset): source と rank input を絞り込む ruleset.
            playstyle (Playstyle): source と rank input を絞り込む playstyle.

        Returns:
            UserStatsSourceRead: 最初の出現順で deduplicate した既存 User の source rows と,
            leaderboard-visible User の rank inputs.

        Notes:
            current projection がある User はその値を使用する. projection がない User は
            条件に一致する Score と performance best から source row を構築する.
            state を変更しない.
        """
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
    """一人の User の current stats source row を projection または Score から構築する.

    Args:
        state (InMemoryCommandRepositoryState): User, Score, projection を含む snapshot.
        user_id (int): source row を構築する User の ID.
        ruleset (Ruleset): 対象 ruleset.
        playstyle (Playstyle): 対象 playstyle.
        projection (UserStatsProjection | None): 優先して使う current stats projection.
        best_performances (tuple[UserPerformanceBest, ...]): projection がない場合に転記する
            performance best.

    Returns:
        UserStatsSourceRow: projection があればその集計値, なければ対象 Score から集計した
            source row.

    Notes:
        projection を使う場合は best_performances を空にする. projection がない場合は Relax と
        Autopilot を除いた一致 Score から rank score, total score, hit totals を計算する.
        state を変更しない.
    """
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
    """Score が初期 UserStats 集計 scope に入るかを判定する.

    Args:
        score (Score): 判定する Score.
        ruleset (Ruleset): 一致させる ruleset.
        playstyle (Playstyle): 一致させる playstyle.

    Returns:
        bool: ruleset/playstyle が一致し, Relax と Autopilot のいずれも持たなければ True.

    Notes:
        score を変更しない.
    """
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
    """Scope に一致する Beatmap performance best を User ごとに PP 降順でまとめる.

    Args:
        rows (Iterable[BeatmapPerformanceBest]): 絞り込む performance best records.
        ruleset (Ruleset): 一致させる ruleset.
        playstyle (Playstyle): 一致させる playstyle.

    Returns:
        dict[int, tuple[UserPerformanceBest, ...]]: User ID ごとに PP 降順の best tuple を持つ
            mapping.

    Notes:
        入力 rows と record を変更しない.
    """
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
    """Scope に一致する current UserStats projection を User ID で索引化する.

    Args:
        rows (Iterable[UserStatsProjection]): 絞り込む current stats projection records.
        ruleset (Ruleset): 一致させる ruleset.
        playstyle (Playstyle): 一致させる playstyle.

    Returns:
        dict[int, UserStatsProjection]: scope が一致する各 User の projection mapping.

    Notes:
        同一 User ID の複数 row があれば, 入力反復順で最後の row を保持する.
        入力 rows を変更しない.
    """
    return {
        row.scope.user_id: row
        for row in rows
        if row.scope.ruleset is ruleset and row.scope.playstyle is playstyle
    }


def _hit_totals(scores: tuple[Score, ...]) -> UserStatsHitTotals:
    """Score 群の hit count fields を合計する.

    Args:
        scores (tuple[Score, ...]): hit count を合計する Score 群.

    Returns:
        UserStatsHitTotals: n300, n100, n50, geki, katu, miss をそれぞれ合計した値.

    Notes:
        scores を変更しない. 空の tuple ではすべて 0 の totals を返す.
    """
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
    """User に割り当てられた Role permissions から leaderboard 可視性を判定する.

    Args:
        state (InMemoryCommandRepositoryState): Role と User Role assignment を含む snapshot.
        user_id (int): 可視性を判定する User の ID.

    Returns:
        bool: 合成した Privileges が leaderboard-visible なら True, それ以外は False.

    Notes:
        存在しない Role ID は無視し, state を変更しない.
    """
    privileges = Privileges.NONE
    for role_id in state.role_ids_by_user_id.get(user_id, set()):
        role = state.roles_by_id.get(role_id)
        if role is not None:
            privileges |= role.permissions
    return is_leaderboard_visible_user(privileges)


__all__ = ("InMemoryUserStatsQueryRepository",)

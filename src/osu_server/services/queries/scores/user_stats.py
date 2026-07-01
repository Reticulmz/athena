"""Transport-neutral current UserStats query use-case。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, final

from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserCurrentStats, UserStatsPolicy

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.repositories.interfaces.queries.user_stats import (
        UserStatsQueryRepository,
        UserStatsRankInput,
        UserStatsSourceRead,
        UserStatsSourceRow,
    )

_ZERO_DECIMAL = Decimal("0")


@dataclass(frozen=True, slots=True)
class CurrentUserStatsQueryInput:
    """Current stats を読む requested user ids と mode scope。"""

    user_ids: tuple[int, ...]
    ruleset: Ruleset = Ruleset.OSU
    playstyle: Playstyle = Playstyle.VANILLA


@dataclass(frozen=True, slots=True)
class CurrentUserStatsQueryResult:
    """Transport-neutral current stats query result。"""

    stats: tuple[UserCurrentStats, ...]

    @property
    def stats_by_user_id(self) -> Mapping[int, UserCurrentStats]:
        """user id から current stats を参照する mapping を返す。"""
        return {stats.user_id: stats for stats in self.stats}

    def get(self, user_id: int) -> UserCurrentStats | None:
        """指定 user id の current stats を返す。存在しなければ None を返す。"""
        return self.stats_by_user_id.get(user_id)


@final
class CurrentUserStatsQuery:
    """Read-only source data から current UserStats を組み立てる。"""

    def __init__(
        self,
        *,
        repository: UserStatsQueryRepository,
        policy: UserStatsPolicy | None = None,
    ) -> None:
        """query repository と stats policy を受け取る。"""
        self._repository: UserStatsQueryRepository = repository
        self._policy: UserStatsPolicy = policy or UserStatsPolicy()

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """requested users の current stats を deduped request order で返す。"""
        user_ids = _deduped_positive_user_ids(input_data.user_ids)
        if len(user_ids) == 0:
            return CurrentUserStatsQueryResult(stats=())

        source_read = await self._repository.read_current_stats_sources(
            user_ids,
            ruleset=input_data.ruleset,
            playstyle=input_data.playstyle,
        )
        return _result_from_source_read(
            user_ids=user_ids,
            source_read=source_read,
            policy=self._policy,
        )


def _deduped_positive_user_ids(user_ids: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(user_id for user_id in user_ids if user_id > 0))


def _result_from_source_read(
    *,
    user_ids: tuple[int, ...],
    source_read: UserStatsSourceRead,
    policy: UserStatsPolicy,
) -> CurrentUserStatsQueryResult:
    sources_by_user_id = {source.user_id: source for source in source_read.users}
    ranks_by_user_id = _global_ranks_by_user_id(
        rank_inputs=source_read.rank_inputs,
        policy=policy,
    )
    return CurrentUserStatsQueryResult(
        stats=tuple(
            _stats_from_source(
                source=sources_by_user_id[user_id],
                global_rank=(
                    sources_by_user_id[user_id].global_rank
                    if sources_by_user_id[user_id].global_rank is not None
                    else ranks_by_user_id.get(user_id)
                ),
                policy=policy,
            )
            for user_id in user_ids
            if user_id in sources_by_user_id
        )
    )


def _stats_from_source(
    *,
    source: UserStatsSourceRow,
    global_rank: int | None,
    policy: UserStatsPolicy,
) -> UserCurrentStats:
    performance_totals = policy.calculate_performance_totals(source.best_performances)
    pp = source.pp if source.pp is not None else performance_totals.total_pp
    accuracy = source.accuracy if source.accuracy is not None else performance_totals.accuracy
    return UserCurrentStats(
        user_id=source.user_id,
        pp=pp,
        accuracy=accuracy,
        global_rank=global_rank if pp > _ZERO_DECIMAL else None,
        play_count=source.play_count,
        ranked_score=source.ranked_score,
        total_score=source.total_score,
        max_combo=source.max_combo,
        play_time_seconds=source.play_time_seconds,
        hit_totals=source.hit_totals,
    )


def _global_ranks_by_user_id(
    *,
    rank_inputs: tuple[UserStatsRankInput, ...],
    policy: UserStatsPolicy,
) -> dict[int, int]:
    candidates = tuple(
        (
            rank_input.user_id,
            rank_input.pp
            if rank_input.pp is not None
            else policy.calculate_performance_totals(rank_input.best_performances).total_pp,
        )
        for rank_input in rank_inputs
    )
    ordered = sorted(
        ((user_id, pp) for user_id, pp in candidates if pp > _ZERO_DECIMAL),
        key=lambda candidate: (-candidate[1], candidate[0]),
    )
    return {user_id: rank for rank, (user_id, _pp) in enumerate(ordered, start=1)}


__all__ = (
    "CurrentUserStatsQuery",
    "CurrentUserStatsQueryInput",
    "CurrentUserStatsQueryResult",
)

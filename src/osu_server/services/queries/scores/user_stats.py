"""Transport-neutral current UserStats query use-case を提供する."""

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
    """Current stats を読む User ID 群と mode scope を表す.

    Attributes:
        user_ids (tuple[int, ...]): 統計を読む User ID 群. 重複とゼロ以下の値は query で除く.
        ruleset (Ruleset): 集計対象の ruleset.
        playstyle (Playstyle): 集計対象の playstyle.
    """

    user_ids: tuple[int, ...]
    ruleset: Ruleset = Ruleset.OSU
    playstyle: Playstyle = Playstyle.VANILLA


@dataclass(frozen=True, slots=True)
class CurrentUserStatsQueryResult:
    """Transport-neutral current stats query の結果を表す.

    Attributes:
        stats (tuple[UserCurrentStats, ...]): 要求順を保った取得済み UserStats 群.
    """

    stats: tuple[UserCurrentStats, ...]

    @property
    def stats_by_user_id(self) -> Mapping[int, UserCurrentStats]:
        """User ID から current stats を参照する mapping を返す.

        Returns:
            Mapping[int, UserCurrentStats]: User ID を key とする current stats の mapping.
        """
        return {stats.user_id: stats for stats in self.stats}

    def get(self, user_id: int) -> UserCurrentStats | None:
        """指定 User ID の current stats を返す.

        Args:
            user_id (int): 取得する User ID.

        Returns:
            UserCurrentStats | None: 一致する current stats. 存在しない場合は None.
        """
        return self.stats_by_user_id.get(user_id)


@final
class CurrentUserStatsQuery:
    """Read-only source data から current UserStats を組み立てる.

    Attributes:
        _repository (UserStatsQueryRepository): current stats の source data を読む repository.
        _policy (UserStatsPolicy): projection 値と順位を計算する policy.
    """

    def __init__(
        self,
        *,
        repository: UserStatsQueryRepository,
        policy: UserStatsPolicy | None = None,
    ) -> None:
        """Query repository と stats policy を設定する.

        Args:
            repository (UserStatsQueryRepository): source data を読む query repository.
            policy (UserStatsPolicy | None): projection に使う policy. None の場合は既定の
                policy を作成する.
        """
        self._repository: UserStatsQueryRepository = repository
        self._policy: UserStatsPolicy = policy or UserStatsPolicy()

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """要求された users の current stats を重複除去後の要求順で返す.

        Args:
            input_data (CurrentUserStatsQueryInput): 対象 User ID 群と score mode scope.

        Returns:
            CurrentUserStatsQueryResult: 正の User ID だけを対象にした current stats 結果.

        Notes:
            repository が返さない User ID は結果から除く. source の global rank があれば
            policy から再計算した順位より優先する.
        """
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
    """正の User ID を重複なしで最初の出現順に並べる.

    Args:
        user_ids (tuple[int, ...]): 重複またはゼロ以下を含み得る User ID 群.

    Returns:
        tuple[int, ...]: 正の値だけを残した重複なしの User ID 群.
    """
    return tuple(dict.fromkeys(user_id for user_id in user_ids if user_id > 0))


def _result_from_source_read(
    *,
    user_ids: tuple[int, ...],
    source_read: UserStatsSourceRead,
    policy: UserStatsPolicy,
) -> CurrentUserStatsQueryResult:
    """Source read と policy から current stats query 結果を組み立てる.

    Args:
        user_ids (tuple[int, ...]): 重複除去済みの要求 User ID 群.
        source_read (UserStatsSourceRead): repository が返した source data と順位入力.
        policy (UserStatsPolicy): projection 値と順位を計算する policy.

    Returns:
        CurrentUserStatsQueryResult: 取得できた users だけを要求順で含む query 結果.
    """
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
    """1 User の source row を transport-neutral current stats へ変換する.

    Args:
        source (UserStatsSourceRow): 変換する UserStats source row.
        global_rank (int | None): source または policy 計算から得た global rank.
        policy (UserStatsPolicy): PP と accuracy の不足値を計算する policy.

    Returns:
        UserCurrentStats: source 値と policy 計算値を統合した current stats.

    Notes:
        source の PP または accuracy がない場合は best performances から補う. PP が正でない
        user には global rank を設定しない.
    """
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
    """Rank input から正の PP を持つ users の global rank を計算する.

    Args:
        rank_inputs (tuple[UserStatsRankInput, ...]): rank 計算に必要な User ごとの入力.
        policy (UserStatsPolicy): 未投影 PP を計算する policy.

    Returns:
        dict[int, int]: PP の降順と User ID の昇順で決めた User ID ごとの順位.
    """
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

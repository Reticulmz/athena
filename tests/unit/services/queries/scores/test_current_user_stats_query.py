"""Current UserStats query use-case tests。"""

from __future__ import annotations

from decimal import Decimal
from typing import final

from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import (
    UserCurrentStats,
    UserPerformanceBest,
    UserStatsHitTotals,
)
from osu_server.repositories.interfaces.queries.user_stats import (
    UserStatsRankInput,
    UserStatsSourceRead,
    UserStatsSourceRow,
)
from osu_server.services.queries.scores.user_stats import (
    CurrentUserStatsQuery,
    CurrentUserStatsQueryInput,
)


@final
class UserStatsQueryRepositoryStub:
    """Typed current stats query repository test double."""

    def __init__(self, result: UserStatsSourceRead) -> None:
        self._result = result
        self.requests: list[tuple[tuple[int, ...], Ruleset, Playstyle]] = []

    async def read_current_stats_sources(
        self,
        user_ids: tuple[int, ...],
        *,
        ruleset: Ruleset = Ruleset.OSU,
        playstyle: Playstyle = Playstyle.VANILLA,
    ) -> UserStatsSourceRead:
        self.requests.append((user_ids, ruleset, playstyle))
        return self._result


async def test_query_dedupes_requested_ids_applies_policy_and_global_rank() -> None:
    repository = UserStatsQueryRepositoryStub(
        UserStatsSourceRead(
            users=(
                _source(
                    user_id=20,
                    bests=(UserPerformanceBest(pp=Decimal("100"), accuracy=0.90),),
                ),
                _source(
                    user_id=10,
                    max_combo=1234,
                    bests=(
                        UserPerformanceBest(pp=Decimal("100"), accuracy=1.0),
                        UserPerformanceBest(pp=Decimal("50"), accuracy=0.5),
                    ),
                ),
            ),
            rank_inputs=(
                UserStatsRankInput(
                    user_id=30,
                    best_performances=(UserPerformanceBest(pp=Decimal("150"), accuracy=0.95),),
                ),
                UserStatsRankInput(
                    user_id=10,
                    best_performances=(
                        UserPerformanceBest(pp=Decimal("100"), accuracy=1.0),
                        UserPerformanceBest(pp=Decimal("50"), accuracy=0.5),
                    ),
                ),
                UserStatsRankInput(
                    user_id=20,
                    best_performances=(UserPerformanceBest(pp=Decimal("100"), accuracy=0.90),),
                ),
            ),
        )
    )
    query = CurrentUserStatsQuery(repository=repository)

    result = await query.execute(CurrentUserStatsQueryInput(user_ids=(10, 20, 10, 999)))

    assert repository.requests == [((10, 20, 999), Ruleset.OSU, Playstyle.VANILLA)]
    assert [stats.user_id for stats in result.stats] == [10, 20]
    assert result.stats_by_user_id[10] == result.stats[0]
    assert result.get(20) == result.stats[1]
    first = result.stats[0]
    assert first.pp == Decimal("100") + Decimal("50") * Decimal("0.95")
    assert first.accuracy == float(
        (Decimal("1.0") + Decimal("0.5") * Decimal("0.95")) / (Decimal("1") + Decimal("0.95"))
    )
    assert first.global_rank == 2
    assert first.play_count == 3
    assert first.ranked_score == 200
    assert first.total_score == 300
    assert first.max_combo == 1234
    assert first.play_time_seconds == 45
    assert result.stats[1].pp == Decimal("100")
    assert result.stats[1].global_rank == 3


async def test_query_uses_projected_pp_accuracy_and_rank_inputs_when_present() -> None:
    repository = UserStatsQueryRepositoryStub(
        UserStatsSourceRead(
            users=(
                _source(
                    user_id=10,
                    bests=(UserPerformanceBest(pp=Decimal("999"), accuracy=1.0),),
                    pp=Decimal("123.45"),
                    accuracy=0.9876,
                ),
            ),
            rank_inputs=(
                UserStatsRankInput(user_id=10, pp=Decimal("123.45")),
                UserStatsRankInput(user_id=20, pp=Decimal("200")),
            ),
        )
    )
    query = CurrentUserStatsQuery(repository=repository)

    result = await query.execute(CurrentUserStatsQueryInput(user_ids=(10,)))

    stats = result.get(10)
    assert stats is not None
    assert stats.pp == Decimal("123.45")
    assert stats.accuracy == 0.9876
    assert stats.global_rank == 2


async def test_query_prefers_source_global_rank_when_repository_provides_it() -> None:
    repository = UserStatsQueryRepositoryStub(
        UserStatsSourceRead(
            users=(
                _source(
                    user_id=10,
                    bests=(UserPerformanceBest(pp=Decimal("999"), accuracy=1.0),),
                    pp=Decimal("123.45"),
                    accuracy=0.9876,
                    global_rank=42,
                ),
            ),
            rank_inputs=(
                UserStatsRankInput(user_id=10, pp=Decimal("123.45")),
                UserStatsRankInput(user_id=20, pp=Decimal("200")),
            ),
        )
    )
    query = CurrentUserStatsQuery(repository=repository)

    result = await query.execute(CurrentUserStatsQueryInput(user_ids=(10,)))

    stats = result.get(10)
    assert stats is not None
    assert stats.global_rank == 42


async def test_empty_known_user_returns_stable_safe_defaults_without_rank() -> None:
    repository = UserStatsQueryRepositoryStub(
        UserStatsSourceRead(
            users=(
                _source(
                    user_id=10,
                    play_count=0,
                    ranked_score=0,
                    total_score=0,
                    play_time_seconds=None,
                    bests=(),
                    hit_totals=UserStatsHitTotals(),
                ),
            ),
            rank_inputs=(),
        )
    )
    query = CurrentUserStatsQuery(repository=repository)

    result = await query.execute(CurrentUserStatsQueryInput(user_ids=(10,)))

    assert result.stats == (UserCurrentStats.empty(user_id=10),)


async def test_non_positive_user_ids_are_omitted_before_repository_read() -> None:
    repository = UserStatsQueryRepositoryStub(UserStatsSourceRead(users=(), rank_inputs=()))
    query = CurrentUserStatsQuery(repository=repository)

    result = await query.execute(CurrentUserStatsQueryInput(user_ids=(0, -1, 10, 10)))

    assert repository.requests == [((10,), Ruleset.OSU, Playstyle.VANILLA)]
    assert result.stats == ()


async def test_query_forwards_requested_ruleset_and_playstyle_to_repository() -> None:
    repository = UserStatsQueryRepositoryStub(UserStatsSourceRead(users=(), rank_inputs=()))
    query = CurrentUserStatsQuery(repository=repository)

    result = await query.execute(
        CurrentUserStatsQueryInput(
            user_ids=(10,),
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
        )
    )

    assert repository.requests == [((10,), Ruleset.MANIA, Playstyle.VANILLA)]
    assert result.stats == ()


def _source(
    *,
    user_id: int,
    play_count: int = 3,
    ranked_score: int = 200,
    total_score: int = 300,
    max_combo: int = 0,
    play_time_seconds: int | None = 45,
    bests: tuple[UserPerformanceBest, ...],
    hit_totals: UserStatsHitTotals | None = None,
    pp: Decimal | None = None,
    accuracy: float | None = None,
    global_rank: int | None = None,
) -> UserStatsSourceRow:
    return UserStatsSourceRow(
        user_id=user_id,
        play_count=play_count,
        ranked_score=ranked_score,
        total_score=total_score,
        max_combo=max_combo,
        play_time_seconds=play_time_seconds,
        best_performances=bests,
        hit_totals=hit_totals
        or UserStatsHitTotals(
            count_300=8,
            count_100=1,
            count_50=1,
        ),
        pp=pp,
        accuracy=accuracy,
        global_rank=global_rank,
    )

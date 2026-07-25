"""CurrentUserStats command repositoryの契約を検証するtests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import (
    UserStatsHitTotals,
    UserStatsProjection,
    UserStatsScope,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


@pytest.mark.asyncio
async def test_replace_persists_projection_by_scope() -> None:
    """scope単位のprojectionがcommit後も取得できる永続化契約を検証する.

    scope固有の値をreplaceしてcommitし, 次のUnit of Workで同じprojectionを読めることを確認する.

    Returns:
        None: 永続化済みのprojectionを検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()
    projection = _projection(pp=Decimal("123.45"), accuracy=0.987)

    async with factory() as uow:
        persisted = await uow.current_user_stats.replace(projection)
        await uow.commit()

    assert persisted == projection
    async with factory() as uow:
        assert await uow.current_user_stats.get(projection.scope) == projection


@pytest.mark.asyncio
async def test_replace_overwrites_existing_projection_for_same_scope() -> None:
    """同じscopeの後続projectionが既存値を置換する契約を検証する.

    初期値をcommit後に異なる統計値でreplaceし, 取得結果がreplacementだけになることを確認する.

    Returns:
        None: scope内の置換結果を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()
    scope = _scope()

    async with factory() as uow:
        _ = await uow.current_user_stats.replace(_projection(scope=scope, pp=Decimal("10")))
        await uow.commit()

    replacement = _projection(
        scope=scope,
        pp=Decimal("20"),
        accuracy=0.95,
        play_count=3,
        hit_totals=UserStatsHitTotals(count_300=30, count_100=3),
    )
    async with factory() as uow:
        _ = await uow.current_user_stats.replace(replacement)
        await uow.commit()

    async with factory() as uow:
        assert await uow.current_user_stats.get(scope) == replacement


@pytest.mark.asyncio
async def test_lock_scope_is_available_before_projection_refresh() -> None:
    """projection更新前にscope lockを取得できるcommand契約を検証する.

    projectionがまだ存在しないscopeでlock操作をcommitし,
    更新処理の先行ロックを許可することを確認する.

    Returns:
        None: lock操作の完了を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()
    scope = _scope()

    async with factory() as uow:
        await uow.current_user_stats.lock_scope(scope)
        await uow.commit()


def _scope() -> UserStatsScope:
    """User 10のosu vanilla統計scopeを構築する.

    Returns:
        UserStatsScope: testで共有するUser 10のosu vanilla統計scope.
    """
    return UserStatsScope(
        user_id=10,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )


def _projection(
    *,
    scope: UserStatsScope | None = None,
    pp: Decimal | None = None,
    accuracy: float = 0.0,
    play_count: int = 0,
    hit_totals: UserStatsHitTotals | None = None,
) -> UserStatsProjection:
    """指定値または既定値を持つUserStatsProjection fixtureを構築する.

    Args:
        scope (UserStatsScope | None): 使用する統計scope. Noneの場合は標準scopeを使う.
        pp (Decimal | None): 保存するperformance point. Noneの場合は0を使う.
        accuracy (float): 保存するaccuracy値.
        play_count (int): 保存するplay数.
        hit_totals (UserStatsHitTotals | None): 保存するhit集計. Noneの場合は標準集計を使う.

    Returns:
        UserStatsProjection: replaceとgetの契約検証に使う統計projection.
    """
    return UserStatsProjection(
        scope=scope or _scope(),
        pp=pp if pp is not None else Decimal("0"),
        accuracy=accuracy,
        play_count=play_count,
        ranked_score=1_000,
        total_score=2_000,
        max_combo=500,
        play_time_seconds=60,
        hit_totals=hit_totals or UserStatsHitTotals(count_300=10),
    )

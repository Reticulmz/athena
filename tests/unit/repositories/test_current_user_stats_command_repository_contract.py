"""CurrentUserStats command repository contract tests。"""

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
    factory = InMemoryUnitOfWorkFactory()
    scope = _scope()

    async with factory() as uow:
        await uow.current_user_stats.lock_scope(scope)
        await uow.commit()


def _scope() -> UserStatsScope:
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

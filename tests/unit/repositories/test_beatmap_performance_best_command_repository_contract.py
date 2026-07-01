"""Beatmap performance best projection の command repository contract tests。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBestBeatmapProjectionSlice,
    BeatmapPerformanceBestScope,
    BeatmapPerformanceBestUserProjectionSlice,
    UpsertBeatmapPerformanceBest,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)


def _memory_factory() -> UnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory()


async def test_unit_of_work_exposes_beatmap_performance_best_repository() -> None:
    factory = _memory_factory()

    async with factory() as uow:
        assert hasattr(uow, "beatmap_performance_bests")


async def test_upsert_replaces_existing_best_only_when_candidate_has_better_pp() -> None:
    factory = _memory_factory()
    scope = _scope()

    async with factory() as uow:
        created = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=scope, score_id=10, pp=Decimal("100.50"), submitted_at=_NOW)
        )
        lower = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=11,
                pp=Decimal("100.49"),
                submitted_at=_NOW - timedelta(seconds=1),
            )
        )
        higher = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=12,
                pp=Decimal("100.51"),
                submitted_at=_NOW + timedelta(seconds=1),
            )
        )
        await uow.commit()

    async with factory() as uow:
        persisted = await uow.beatmap_performance_bests.get_best(scope)

    assert created.score_id == 10
    assert lower.score_id == 10
    assert higher.score_id == 12
    assert persisted == higher


async def test_upsert_uses_earlier_submission_and_lower_score_id_as_tie_breakers() -> None:
    factory = _memory_factory()
    scope = _scope()

    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=scope, score_id=20, pp=Decimal("150.25"), submitted_at=_NOW)
        )
        later = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=19,
                pp=Decimal("150.25"),
                submitted_at=_NOW + timedelta(seconds=1),
            )
        )
        earlier = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=30,
                pp=Decimal("150.25"),
                submitted_at=_NOW - timedelta(seconds=1),
            )
        )
        lower_score_id = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=18,
                pp=Decimal("150.25"),
                submitted_at=_NOW - timedelta(seconds=1),
            )
        )
        higher_score_id = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=31,
                pp=Decimal("150.25"),
                submitted_at=_NOW - timedelta(seconds=1),
            )
        )
        await uow.commit()

    assert later.score_id == 20
    assert earlier.score_id == 30
    assert lower_score_id.score_id == 18
    assert higher_score_id.score_id == 18


async def test_replace_projection_slice_replaces_only_target_user_rows() -> None:
    factory = _memory_factory()
    stale_scope = _scope(user_id=1000, beatmap_id=1)
    rebuilt_scope = _scope(user_id=1000, beatmap_id=2)
    unaffected_scope = _scope(user_id=2000, beatmap_id=1)

    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=stale_scope, score_id=40, pp=Decimal("100"), submitted_at=_NOW)
        )
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=rebuilt_scope, score_id=41, pp=Decimal("110"), submitted_at=_NOW)
        )
        unaffected = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=unaffected_scope, score_id=42, pp=Decimal("120"), submitted_at=_NOW)
        )
        await uow.commit()

    replacement = _upsert(
        scope=rebuilt_scope,
        score_id=43,
        pp=Decimal("130"),
        submitted_at=_NOW + timedelta(seconds=1),
    )
    async with factory() as uow:
        await uow.beatmap_performance_bests.replace_projection_slice(
            BeatmapPerformanceBestUserProjectionSlice(user_id=1000),
            (replacement,),
        )
        await uow.commit()

    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(stale_scope) is None
        rebuilt = await uow.beatmap_performance_bests.get_best(rebuilt_scope)
        assert rebuilt is not None
        assert rebuilt.score_id == 43
        assert await uow.beatmap_performance_bests.get_best(unaffected_scope) == unaffected


async def test_replace_projection_slice_can_delete_stale_beatmap_rows_with_empty_rows() -> None:
    factory = _memory_factory()
    stale_scope = _scope(beatmap_id=1)
    unaffected_scope = _scope(beatmap_id=2)

    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=stale_scope, score_id=50, pp=Decimal("100"), submitted_at=_NOW)
        )
        unaffected = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=unaffected_scope, score_id=51, pp=Decimal("120"), submitted_at=_NOW)
        )
        await uow.commit()

    async with factory() as uow:
        await uow.beatmap_performance_bests.replace_projection_slice(
            BeatmapPerformanceBestBeatmapProjectionSlice(beatmap_ids=(1,)),
            (),
        )
        await uow.commit()

    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(stale_scope) is None
        assert await uow.beatmap_performance_bests.get_best(unaffected_scope) == unaffected


async def test_replace_scope_replaces_only_exact_scope() -> None:
    factory = _memory_factory()
    target_scope = _scope(beatmap_id=1)
    unaffected_scope = _scope(beatmap_id=2)

    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=target_scope, score_id=52, pp=Decimal("100"), submitted_at=_NOW)
        )
        unaffected = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=unaffected_scope, score_id=53, pp=Decimal("120"), submitted_at=_NOW)
        )
        await uow.commit()

    replacement = _upsert(
        scope=target_scope,
        score_id=54,
        pp=Decimal("130"),
        submitted_at=_NOW + timedelta(seconds=1),
    )
    async with factory() as uow:
        replaced = await uow.beatmap_performance_bests.replace_scope(
            target_scope,
            replacement,
        )
        await uow.commit()

    assert replaced is not None
    assert replaced.score_id == 54
    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(target_scope) == replaced
        assert await uow.beatmap_performance_bests.get_best(unaffected_scope) == unaffected


async def test_replace_scope_deletes_exact_scope_with_empty_winner() -> None:
    factory = _memory_factory()
    scope = _scope()

    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=scope, score_id=55, pp=Decimal("100"), submitted_at=_NOW)
        )
        await uow.commit()

    async with factory() as uow:
        result = await uow.beatmap_performance_bests.replace_scope(scope, None)
        await uow.commit()

    assert result is None
    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(scope) is None


async def test_uncommitted_projection_rows_roll_back_with_unit_of_work() -> None:
    factory = _memory_factory()
    scope = _scope()

    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=scope, score_id=60, pp=Decimal("100"), submitted_at=_NOW)
        )
        await uow.rollback()

    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(scope) is None


async def test_list_user_bests_returns_mode_scoped_rows_in_pp_order() -> None:
    factory = _memory_factory()

    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=_scope(beatmap_id=1), score_id=70, pp=Decimal("100"), submitted_at=_NOW)
        )
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(scope=_scope(beatmap_id=2), score_id=71, pp=Decimal("150"), submitted_at=_NOW)
        )
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(
                scope=_scope(user_id=2000, beatmap_id=1),
                score_id=72,
                pp=Decimal("999"),
                submitted_at=_NOW,
            )
        )
        _ = await uow.beatmap_performance_bests.upsert_if_better(
            _upsert(
                scope=BeatmapPerformanceBestScope(
                    user_id=1000,
                    beatmap_id=3,
                    ruleset=Ruleset.MANIA,
                    playstyle=Playstyle.VANILLA,
                ),
                score_id=73,
                pp=Decimal("200"),
                submitted_at=_NOW,
            )
        )
        await uow.commit()

    async with factory() as uow:
        bests = await uow.beatmap_performance_bests.list_user_bests(
            user_id=1000,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
        )

    assert [best.score_id for best in bests] == [71, 70]


def _scope(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
) -> BeatmapPerformanceBestScope:
    return BeatmapPerformanceBestScope(
        user_id=user_id,
        beatmap_id=beatmap_id,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )


def _upsert(
    *,
    scope: BeatmapPerformanceBestScope,
    score_id: int,
    pp: Decimal,
    submitted_at: datetime,
    performance_calculation_id: int | None = None,
    accuracy: float = 0.98,
    score: int = 1_000_000,
) -> UpsertBeatmapPerformanceBest:
    return UpsertBeatmapPerformanceBest(
        scope=scope,
        score_id=score_id,
        performance_calculation_id=performance_calculation_id or score_id + 10_000,
        pp=pp,
        accuracy=accuracy,
        score=score,
        submitted_at=submitted_at,
    )

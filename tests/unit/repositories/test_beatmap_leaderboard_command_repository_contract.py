"""Command repository contract tests for Beatmap Leaderboard projections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from osu_server.domain.scores.leaderboards import ALL_MODS_FILTER_KEY, ScoreRankKey
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardBeatmapProjectionSlice,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)


def _memory_factory() -> UnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory()


async def test_upsert_replaces_existing_user_best_only_when_candidate_ranks_higher() -> None:
    factory = _memory_factory()
    scope = _scope()

    async with factory() as uow:
        created = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=scope, score_id=10, score=1_000, submitted_at=_NOW)
        )
        lower = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=scope, score_id=11, score=900, submitted_at=_NOW + timedelta(seconds=1))
        )
        higher = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=12,
                score=1_100,
                submitted_at=_NOW + timedelta(seconds=2),
            )
        )
        await uow.commit()

    async with factory() as uow:
        persisted = await uow.beatmap_leaderboards.get_user_best(scope)

    assert created.score_id == 10
    assert lower.score_id == 10
    assert higher.score_id == 12
    assert persisted == higher


async def test_upsert_uses_submitted_at_and_lower_score_id_as_tie_breakers() -> None:
    factory = _memory_factory()
    scope = _scope()

    async with factory() as uow:
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=scope, score_id=20, score=1_000, submitted_at=_NOW)
        )
        later = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=19,
                score=1_000,
                submitted_at=_NOW + timedelta(seconds=1),
            )
        )
        earlier = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=30,
                score=1_000,
                submitted_at=_NOW - timedelta(seconds=1),
            )
        )
        lower_score_id = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=18,
                score=1_000,
                submitted_at=_NOW - timedelta(seconds=1),
            )
        )
        higher_score_id = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(
                scope=scope,
                score_id=31,
                score=1_000,
                submitted_at=_NOW - timedelta(seconds=1),
            )
        )
        await uow.commit()

    assert later.score_id == 20
    assert earlier.score_id == 30
    assert lower_score_id.score_id == 18
    assert higher_score_id.score_id == 18


async def test_same_score_can_project_into_multiple_mod_filter_keys() -> None:
    factory = _memory_factory()
    all_mods_scope = _scope()
    selected_mods_scope = _scope(mod_filter_key=64)

    async with factory() as uow:
        all_mods = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=all_mods_scope, score_id=40, score=1_000, submitted_at=_NOW)
        )
        selected_mods = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=selected_mods_scope, score_id=40, score=1_000, submitted_at=_NOW)
        )
        await uow.commit()

    async with factory() as uow:
        persisted_all_mods = await uow.beatmap_leaderboards.get_user_best(all_mods_scope)
        persisted_selected_mods = await uow.beatmap_leaderboards.get_user_best(selected_mods_scope)

    assert all_mods.score_id == selected_mods.score_id == 40
    assert all_mods.id != selected_mods.id
    assert persisted_all_mods == all_mods
    assert persisted_selected_mods == selected_mods


async def test_replace_projection_slice_can_delete_stale_user_rows_with_empty_rows() -> None:
    factory = _memory_factory()
    user_scope = _scope(user_id=1000, beatmap_id=1)
    other_user_scope = _scope(user_id=2000, beatmap_id=1)

    async with factory() as uow:
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=user_scope, score_id=50, score=1_000, submitted_at=_NOW)
        )
        other_user = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=other_user_scope, score_id=51, score=1_000, submitted_at=_NOW)
        )
        await uow.commit()

    async with factory() as uow:
        await uow.beatmap_leaderboards.replace_projection_slice(
            BeatmapLeaderboardUserProjectionSlice(user_id=1000),
            (),
        )
        await uow.commit()

    async with factory() as uow:
        assert await uow.beatmap_leaderboards.get_user_best(user_scope) is None
        assert await uow.beatmap_leaderboards.get_user_best(other_user_scope) == other_user


async def test_replace_projection_slice_replaces_only_target_beatmap_ids() -> None:
    factory = _memory_factory()
    stale_scope = _scope(user_id=1000, beatmap_id=1)
    rebuilt_scope = _scope(user_id=1000, beatmap_id=2)
    unaffected_scope = _scope(user_id=1000, beatmap_id=3)

    async with factory() as uow:
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=stale_scope, score_id=60, score=1_000, submitted_at=_NOW)
        )
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=rebuilt_scope, score_id=61, score=1_000, submitted_at=_NOW)
        )
        unaffected = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=unaffected_scope, score_id=62, score=1_000, submitted_at=_NOW)
        )
        await uow.commit()

    replacement = _upsert(
        scope=rebuilt_scope,
        score_id=63,
        score=1_200,
        submitted_at=_NOW + timedelta(seconds=1),
    )
    async with factory() as uow:
        await uow.beatmap_leaderboards.replace_projection_slice(
            BeatmapLeaderboardBeatmapProjectionSlice(beatmap_ids=(1, 2)),
            (replacement,),
        )
        await uow.commit()

    async with factory() as uow:
        assert await uow.beatmap_leaderboards.get_user_best(stale_scope) is None
        rebuilt = await uow.beatmap_leaderboards.get_user_best(rebuilt_scope)
        assert rebuilt is not None
        assert rebuilt.score_id == 63
        assert await uow.beatmap_leaderboards.get_user_best(unaffected_scope) == unaffected


async def test_uncommitted_projection_rows_roll_back_with_unit_of_work() -> None:
    factory = _memory_factory()
    scope = _scope()

    async with factory() as uow:
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=scope, score_id=70, score=1_000, submitted_at=_NOW)
        )
        await uow.rollback()

    async with factory() as uow:
        assert await uow.beatmap_leaderboards.get_user_best(scope) is None


def _scope(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
    mod_filter_key: int = ALL_MODS_FILTER_KEY,
) -> BeatmapLeaderboardUserBestScope:
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=beatmap_id,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=user_id,
        mod_filter_key=mod_filter_key,
    )


def _upsert(
    *,
    scope: BeatmapLeaderboardUserBestScope,
    score_id: int,
    score: int,
    submitted_at: datetime,
) -> UpsertBeatmapLeaderboardUserBest:
    return UpsertBeatmapLeaderboardUserBest(
        scope=scope,
        score_id=score_id,
        rank_key=ScoreRankKey(score=score, submitted_at=submitted_at, score_id=score_id),
    )

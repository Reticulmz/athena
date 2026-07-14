"""Command repository contract tests for Beatmap Leaderboard projections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardBeatmapProjectionSlice,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserProjectionSlice,
    BeatmapLeaderboardUserScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)


def _memory_factory() -> UnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory()


@pytest.mark.parametrize(
    "checksum",
    ["", "a" * 31, "a" * 33, "A" * 32, "g" * 32],
)
def test_user_scope_rejects_malformed_beatmap_checksum(checksum: str) -> None:
    """Command scopeがMD5 checksum形式を境界で検証することを確認する.

    Args:
        checksum (str): 空, 長さ違い, 大文字, または非16進数の入力.

    Returns:
        None: malformed checksumがValueErrorになることを示す.

    Raises:
        AssertionError: malformed checksumがscopeとして受理された場合.
    """
    with pytest.raises(ValueError, match="beatmap_checksum"):
        _ = BeatmapLeaderboardUserScope(
            beatmap_id=1,
            beatmap_checksum=checksum,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
            user_id=1,
        )


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


async def test_upsert_replaces_stale_revision_even_when_candidate_score_is_lower() -> None:
    factory = _memory_factory()
    stale_scope = _scope(beatmap_checksum="a" * 32)
    current_scope = _scope(beatmap_checksum="b" * 32)

    async with factory() as uow:
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=stale_scope, score_id=20, score=2_000, submitted_at=_NOW)
        )
        current = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(
                scope=current_scope,
                score_id=21,
                score=1_000,
                submitted_at=_NOW + timedelta(seconds=1),
            )
        )
        await uow.commit()

    async with factory() as uow:
        stale = await uow.beatmap_leaderboards.get_user_best(stale_scope)
        persisted = await uow.beatmap_leaderboards.get_user_best(current_scope)

    assert stale is None
    assert current.score_id == 21
    assert current.scope == current_scope
    assert persisted == current


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


async def test_same_score_is_persisted_once_per_user_scope() -> None:
    factory = _memory_factory()
    scope = _scope()

    async with factory() as uow:
        first = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=scope, score_id=40, score=1_000, submitted_at=_NOW)
        )
        repeated = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=scope, score_id=40, score=1_000, submitted_at=_NOW)
        )
        await uow.commit()

    async with factory() as uow:
        persisted = await uow.beatmap_leaderboards.get_user_best(scope)

    assert repeated == first
    assert persisted == first


async def test_different_mod_scopes_keep_one_row_each_and_share_global_best() -> None:
    factory = _memory_factory()
    no_mod_scope = _scope(mods=Mod.NONE)
    hidden_scope = _scope(mods=Mod.HIDDEN)

    async with factory() as uow:
        no_mod = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=no_mod_scope, score_id=41, score=1_000, submitted_at=_NOW)
        )
        hidden = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=hidden_scope, score_id=42, score=1_100, submitted_at=_NOW)
        )
        global_best = await uow.beatmap_leaderboards.get_global_user_best(_user_scope())
        await uow.commit()

    assert no_mod.score_id == 41
    assert hidden.score_id == 42
    assert global_best == hidden


async def test_same_score_id_cannot_be_used_by_two_mod_scopes() -> None:
    factory = _memory_factory()

    async with factory() as uow:
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _upsert(scope=_scope(mods=Mod.NONE), score_id=43, score=1_000, submitted_at=_NOW)
        )
        with pytest.raises(ValueError, match="score_id is already used"):
            _ = await uow.beatmap_leaderboards.upsert_if_better(
                _upsert(
                    scope=_scope(mods=Mod.HIDDEN),
                    score_id=43,
                    score=1_000,
                    submitted_at=_NOW,
                )
            )


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
    beatmap_checksum: str | None = None,
    mods: Mod = Mod.NONE,
) -> BeatmapLeaderboardUserBestScope:
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=beatmap_id,
        beatmap_checksum=beatmap_checksum or f"{beatmap_id:032x}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=user_id,
        mods=ModCombination(mods),
    )


def _user_scope(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
    beatmap_checksum: str | None = None,
) -> BeatmapLeaderboardUserScope:
    return BeatmapLeaderboardUserScope(
        beatmap_id=beatmap_id,
        beatmap_checksum=beatmap_checksum or f"{beatmap_id:032x}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=user_id,
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

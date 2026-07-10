"""Tests for Beatmap Leaderboard rebuild command workflows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.leaderboards import ALL_MODS_FILTER_KEY, ScoreRankKey
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserCommand,
    RebuildBeatmapLeaderboardsForUserUseCase,
)

_NOW = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)
_CHECKSUM_1 = "a" * 32
_CHECKSUM_2 = "b" * 32


@pytest.mark.asyncio
async def test_user_rebuild_recalculates_user_slice_from_source_scores() -> None:
    factory = InMemoryUnitOfWorkFactory()
    await _seed_scores(
        factory,
        _score(score_id=1, user_id=1000, score=900, checksum="online-1"),
        _score(score_id=2, user_id=1000, score=1_100, checksum="online-2"),
        _score(
            score_id=3,
            user_id=1000,
            score=1_000,
            checksum="online-3",
            mods=ModCombination(Mod.HIDDEN | Mod.NIGHTCORE),
        ),
        _score(score_id=4, user_id=2000, score=2_000, checksum="online-4"),
    )
    await _seed_projection(
        factory,
        _projection(user_id=1000, beatmap_id=1, score_id=99, score=9_999),
        _projection(user_id=2000, beatmap_id=1, score_id=4, score=2_000),
    )

    result = await RebuildBeatmapLeaderboardsForUserUseCase(factory).execute(
        RebuildBeatmapLeaderboardsForUserCommand(user_id=1000, reason="visibility_changed")
    )

    assert result.target_found is True
    assert result.source_score_count == 3
    assert result.projection_row_count == 3
    rows = _projection_rows(factory)
    assert rows[_scope(user_id=1000, beatmap_id=1)].score_id == 2
    assert rows[_scope(user_id=1000, beatmap_id=1, mod_filter_key=0)].score_id == 2
    selected_scope = _scope(
        user_id=1000,
        beatmap_id=1,
        mod_filter_key=int(Mod.HIDDEN | Mod.DOUBLE_TIME),
    )
    assert rows[selected_scope].score_id == 3
    assert rows[_scope(user_id=2000, beatmap_id=1)].score_id == 4
    assert 1 in factory.snapshot().scores_by_id


@pytest.mark.asyncio
async def test_beatmapset_rebuild_recalculates_only_beatmapset_slice() -> None:
    factory = InMemoryUnitOfWorkFactory()
    await _seed_beatmapset(factory, beatmap_ids=(1, 2))
    await _seed_scores(
        factory,
        _score(score_id=1, user_id=1000, beatmap_id=1, score=1_000, checksum="online-1"),
        _score(score_id=2, user_id=1000, beatmap_id=2, score=1_100, checksum="online-2"),
        _score(score_id=3, user_id=1000, beatmap_id=3, score=1_200, checksum="online-3"),
    )
    await _seed_projection(
        factory,
        _projection(user_id=1000, beatmap_id=1, score_id=91, score=9_100),
        _projection(user_id=1000, beatmap_id=2, score_id=92, score=9_200),
        _projection(user_id=1000, beatmap_id=3, score_id=3, score=1_200),
    )

    result = await RebuildBeatmapLeaderboardsForBeatmapsetUseCase(factory).execute(
        RebuildBeatmapLeaderboardsForBeatmapsetCommand(
            beatmapset_id=10,
            reason="beatmapset_changed",
        )
    )

    assert result.target_found is True
    assert result.source_score_count == 2
    assert result.projection_row_count == 4
    rows = _projection_rows(factory)
    assert rows[_scope(user_id=1000, beatmap_id=1)].score_id == 1
    assert rows[_scope(user_id=1000, beatmap_id=2)].score_id == 2
    assert rows[_scope(user_id=1000, beatmap_id=3)].score_id == 3


@pytest.mark.asyncio
async def test_empty_candidate_rebuild_deletes_stale_rows_without_deleting_scores() -> None:
    factory = InMemoryUnitOfWorkFactory()
    await _seed_scores(
        factory,
        _score(
            score_id=1,
            user_id=1000,
            score=1_000,
            checksum="online-1",
            leaderboard_eligible_at_submission=False,
        ),
        _score(score_id=2, user_id=1000, score=1_100, checksum="online-2", passed=False),
    )
    await _seed_projection(factory, _projection(user_id=1000, beatmap_id=1, score_id=90))

    result = await RebuildBeatmapLeaderboardsForUserUseCase(factory).execute(
        RebuildBeatmapLeaderboardsForUserCommand(user_id=1000, reason="visibility_changed")
    )

    assert result.target_found is True
    assert result.source_score_count == 0
    assert result.projection_row_count == 0
    assert _projection_rows(factory) == {}
    assert sorted(factory.snapshot().scores_by_id) == [1, 2]


@pytest.mark.asyncio
async def test_duplicate_rebuild_converges_to_same_public_projection_result() -> None:
    factory = InMemoryUnitOfWorkFactory()
    await _seed_scores(
        factory,
        _score(score_id=1, user_id=1000, score=1_000, checksum="online-1"),
        _score(score_id=2, user_id=1000, score=1_100, checksum="online-2"),
    )

    use_case = RebuildBeatmapLeaderboardsForUserUseCase(factory)
    first_result = await use_case.execute(
        RebuildBeatmapLeaderboardsForUserCommand(user_id=1000, reason="duplicate_job")
    )
    first_rows = _public_projection_result(factory)

    second_result = await use_case.execute(
        RebuildBeatmapLeaderboardsForUserCommand(user_id=1000, reason="duplicate_job")
    )
    second_rows = _public_projection_result(factory)

    assert first_result == second_result
    assert first_rows == second_rows


@pytest.mark.asyncio
async def test_missing_beatmapset_rebuild_is_noop_success() -> None:
    factory = InMemoryUnitOfWorkFactory()
    result = await RebuildBeatmapLeaderboardsForBeatmapsetUseCase(factory).execute(
        RebuildBeatmapLeaderboardsForBeatmapsetCommand(beatmapset_id=404, reason="missing")
    )

    assert result.target_found is False
    assert result.source_score_count == 0
    assert result.projection_row_count == 0


async def _seed_scores(factory: InMemoryUnitOfWorkFactory, *scores: Score) -> None:
    async with factory() as uow:
        for score in scores:
            _ = await uow.scores.create(score)
        await uow.commit()


async def _seed_projection(
    factory: InMemoryUnitOfWorkFactory,
    *rows: UpsertBeatmapLeaderboardUserBest,
) -> None:
    async with factory() as uow:
        for row in rows:
            _ = await uow.beatmap_leaderboards.upsert_if_better(row)
        await uow.commit()


async def _seed_beatmapset(
    factory: InMemoryUnitOfWorkFactory,
    *,
    beatmap_ids: tuple[int, ...],
) -> None:
    beatmaps = tuple(_beatmap(beatmap_id=beatmap_id) for beatmap_id in beatmap_ids)
    async with factory() as uow:
        await uow.beatmaps.save_beatmapset_snapshot(
            BeatmapSet(
                id=10,
                artist="artist",
                title="title",
                creator="creator",
                artist_unicode=None,
                title_unicode=None,
                official_status=BeatmapRankStatus.RANKED,
                official_status_source=BeatmapMetadataSource.OFFICIAL,
                official_status_verified=BeatmapSourceVerification.VERIFIED,
                beatmaps=beatmaps,
                last_fetched_at=None,
                next_refresh_at=None,
            )
        )
        await uow.commit()


def _projection_rows(
    factory: InMemoryUnitOfWorkFactory,
) -> dict[BeatmapLeaderboardUserBestScope, UpsertBeatmapLeaderboardUserBest]:
    snapshot = factory.snapshot()
    return {
        row.scope: UpsertBeatmapLeaderboardUserBest(
            scope=row.scope,
            score_id=row.score_id,
            rank_key=row.rank_key,
        )
        for row in snapshot.beatmap_leaderboard_user_bests_by_id.values()
    }


def _public_projection_result(
    factory: InMemoryUnitOfWorkFactory,
) -> tuple[tuple[tuple[int, int, int, int, int], int], ...]:
    return tuple(
        sorted(
            (
                (
                    row.scope.beatmap_id,
                    row.scope.ruleset.value,
                    row.scope.playstyle.value,
                    row.scope.user_id,
                    row.scope.mod_filter_key,
                ),
                row.score_id,
            )
            for row in factory.snapshot().beatmap_leaderboard_user_bests_by_id.values()
        )
    )


def _scope(
    *,
    user_id: int,
    beatmap_id: int,
    mod_filter_key: int = ALL_MODS_FILTER_KEY,
) -> BeatmapLeaderboardUserBestScope:
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=beatmap_id,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=user_id,
        mod_filter_key=mod_filter_key,
    )


def _projection(
    *,
    user_id: int,
    beatmap_id: int,
    score_id: int,
    score: int = 9_000,
    mod_filter_key: int = ALL_MODS_FILTER_KEY,
) -> UpsertBeatmapLeaderboardUserBest:
    submitted_at = _NOW + timedelta(seconds=score_id)
    return UpsertBeatmapLeaderboardUserBest(
        scope=_scope(user_id=user_id, beatmap_id=beatmap_id, mod_filter_key=mod_filter_key),
        score_id=score_id,
        rank_key=ScoreRankKey(score=score, submitted_at=submitted_at, score_id=score_id),
    )


def _score(
    *,
    score_id: int,
    checksum: str,
    user_id: int = 1000,
    beatmap_id: int = 1,
    beatmap_checksum: str = _CHECKSUM_1,
    score: int = 500_000,
    passed: bool = True,
    leaderboard_eligible_at_submission: bool = True,
    mods: ModCombination | None = None,
) -> Score:
    return Score(
        id=None,
        user_id=user_id,
        beatmap_id=beatmap_id,
        beatmap_checksum=beatmap_checksum,
        online_checksum=checksum,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=mods or ModCombination.none(),
        n300=100,
        n100=10,
        n50=5,
        geki=0,
        katu=0,
        miss=2,
        score=score,
        max_combo=99,
        accuracy=0.95,
        grade=Grade.A,
        passed=passed,
        perfect=False,
        client_version="20240101",
        submitted_at=_NOW + timedelta(seconds=score_id),
        beatmap_status_at_submission="ranked",
        leaderboard_eligible_at_submission=leaderboard_eligible_at_submission,
    )


def _beatmap(*, beatmap_id: int) -> Beatmap:
    checksum = _CHECKSUM_1 if beatmap_id == 1 else _CHECKSUM_2
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=10,
        checksum_md5=checksum,
        mode="osu",
        version=f"version-{beatmap_id}",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.AVAILABLE,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )

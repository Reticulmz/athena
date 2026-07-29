"""beatmap leaderboard再構築command workflowのUnit testを検証する."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.leaderboards import ScoreRankKey
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
    """user単位の再構築がsource scoreからprojection sliceを置換する契約を検証する.

    同一userの通常scoreとmod別score,別userのscore,古いprojectionを登録する条件で,対象userの
    two scopeだけが最新scoreへ置換され,別userのprojectionとsource scoreが保持されることを確認する.

    Returns:
        None: 再構築結果とprojection sliceを検証して,呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    await _seed_beatmapset(factory, beatmap_ids=(1,))
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
    assert result.projection_row_count == 2
    rows = _projection_rows(factory)
    assert rows[_scope(user_id=1000, beatmap_id=1)].score_id == 2
    assert (
        rows[
            _scope(
                user_id=1000,
                beatmap_id=1,
                mods=ModCombination(Mod.HIDDEN | Mod.NIGHTCORE),
            )
        ].score_id
        == 3
    )
    assert rows[_scope(user_id=2000, beatmap_id=1)].score_id == 4
    assert 1 in factory.snapshot().scores_by_id


@pytest.mark.asyncio
async def test_beatmapset_rebuild_recalculates_only_beatmapset_slice() -> None:
    """beatmapset単位の再構築が含有beatmapだけを置換する契約を検証する.

    対象beatmapsetの二つのbeatmapと対象外beatmapのscoreおよび古いprojectionを登録する条件で,
    対象sliceのみ最新scoreへ置換され,対象外rowが保持されることを確認する.

    Returns:
        None: 範囲限定されたprojection置換を検証して,呼び出し側へ値を返さずに完了する.
    """
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
    assert result.projection_row_count == 2
    rows = _projection_rows(factory)
    assert rows[_scope(user_id=1000, beatmap_id=1)].score_id == 1
    assert rows[_scope(user_id=1000, beatmap_id=2)].score_id == 2
    assert rows[_scope(user_id=1000, beatmap_id=3)].score_id == 3


@pytest.mark.asyncio
async def test_empty_candidate_rebuild_deletes_stale_rows_without_deleting_scores() -> None:
    """候補なしの再構築が古いprojectionだけを削除する契約を検証する.

    leaderboard対象外または未passのscoreと古いprojectionを登録する条件で,projectionが空になり,
    source scoreは削除されないことを確認する.

    Returns:
        None: 空候補時のprojection削除とscore保持を検証して,呼び出し側へ値を返さずに完了する.
    """
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
    """重複したuser再構築が同一公開projectionへ収束する契約を検証する.

    同じ再構築commandを連続して実行する条件で,二回のresultと公開projection snapshotが等しく,
    retryが新しい差分を作らないことを確認する.

    Returns:
        None: 重複実行後の同一resultとprojectionを検証して,呼び出し側へ値を返さずに完了する.
    """
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
    """存在しないbeatmapsetの再構築が成功扱いのno-opとなる契約を検証する.

    未登録beatmapsetを指定する条件で,target未発見と0件のsource scoreおよびprojection rowが
    resultとして観測できることを確認する.

    Returns:
        None: no-op success resultを検証して,呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    result = await RebuildBeatmapLeaderboardsForBeatmapsetUseCase(factory).execute(
        RebuildBeatmapLeaderboardsForBeatmapsetCommand(beatmapset_id=404, reason="missing")
    )

    assert result.target_found is False
    assert result.source_score_count == 0
    assert result.projection_row_count == 0


async def _seed_scores(factory: InMemoryUnitOfWorkFactory, *scores: Score) -> None:
    """再構築候補となるsource scoreをmemory UoWへ登録する.

    Args:
        factory (InMemoryUnitOfWorkFactory): scoreを永続化するmemory Unit of Work factory.
        scores (Score): 作成してcommitするscore列.

    Returns:
        None: 全scoreをcommitして,呼び出し側へ値を返さずに完了する.
    """
    async with factory() as uow:
        for score in scores:
            _ = await uow.scores.create(score)
        await uow.commit()


async def _seed_projection(
    factory: InMemoryUnitOfWorkFactory,
    *rows: UpsertBeatmapLeaderboardUserBest,
) -> None:
    """既存のbeatmap leaderboard projection rowをmemory UoWへ登録する.

    Args:
        factory (InMemoryUnitOfWorkFactory): projectionを永続化するmemory Unit of Work factory.
        rows (UpsertBeatmapLeaderboardUserBest): upsertしてcommitするprojection row列.

    Returns:
        None: projection rowをcommitして,呼び出し側へ値を返さずに完了する.
    """
    async with factory() as uow:
        for row in rows:
            _ = await uow.beatmap_leaderboards.upsert_if_better(row)
        await uow.commit()


async def _seed_beatmapset(
    factory: InMemoryUnitOfWorkFactory,
    *,
    beatmap_ids: tuple[int, ...],
) -> None:
    """再構築対象としてbeatmapset snapshotをmemory UoWへ登録する.

    Args:
        factory (InMemoryUnitOfWorkFactory): beatmapset snapshotを保存するmemory Unit of Work
            factory.
        beatmap_ids (tuple[int, ...]): 作成するbeatmapのID列.

    Returns:
        None: beatmapset snapshotをcommitして,呼び出し側へ値を返さずに完了する.
    """
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
    """Memory stateのprojectionをscope単位の比較用mappingへ変換する.

    Args:
        factory (InMemoryUnitOfWorkFactory): projection snapshotを取得するmemory Unit of Work
            factory.

    Returns:
        dict[BeatmapLeaderboardUserBestScope, UpsertBeatmapLeaderboardUserBest]: scopeをkeyにした
        projection row mapping.
    """
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
    """公開比較に必要なprojectionの安定したtuple表現を返す.

    Args:
        factory (InMemoryUnitOfWorkFactory): projection snapshotを取得するmemory Unit of Work
            factory.

    Returns:
        tuple[tuple[tuple[int, int, int, int, int], int], ...]: scopeの永続化keyとscore IDを並べた
        sort済み表現.
    """
    return tuple(
        sorted(
            (
                (
                    row.scope.beatmap_id,
                    row.scope.ruleset.value,
                    row.scope.playstyle.value,
                    row.scope.user_id,
                    row.scope.mods.to_persistence_bitmask(),
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
    mods: ModCombination | None = None,
) -> BeatmapLeaderboardUserBestScope:
    """test用のbeatmap leaderboard user best scopeを作成する.

    Args:
        user_id (int): scopeに含めるuser ID.
        beatmap_id (int): scopeに含めるbeatmap ID.
        mods (ModCombination | None): scopeに含めるmod組み合わせ. 未指定時はno-mod.

    Returns:
        BeatmapLeaderboardUserBestScope: checksum,ruleset,playstyleを含むtest用scope.
    """
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=beatmap_id,
        beatmap_checksum=_CHECKSUM_1 if beatmap_id == 1 else _CHECKSUM_2,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=user_id,
        mods=mods or ModCombination.none(),
    )


def _projection(
    *,
    user_id: int,
    beatmap_id: int,
    score_id: int,
    score: int = 9_000,
    mods: ModCombination | None = None,
) -> UpsertBeatmapLeaderboardUserBest:
    """test用の既存beatmap leaderboard projection rowを作成する.

    Args:
        user_id (int): projection scopeに含めるuser ID.
        beatmap_id (int): projection scopeに含めるbeatmap ID.
        score_id (int): projectionが参照するscore ID.
        score (int): rank keyに使うscore値.
        mods (ModCombination | None): projection scopeのmod組み合わせ. 未指定時はno-mod.

    Returns:
        UpsertBeatmapLeaderboardUserBest: upsert可能なtest用projection row.
    """
    submitted_at = _NOW + timedelta(seconds=score_id)
    return UpsertBeatmapLeaderboardUserBest(
        scope=_scope(user_id=user_id, beatmap_id=beatmap_id, mods=mods),
        score_id=score_id,
        rank_key=ScoreRankKey(score=score, submitted_at=submitted_at, score_id=score_id),
    )


def _score(
    *,
    score_id: int,
    checksum: str,
    user_id: int = 1000,
    beatmap_id: int = 1,
    beatmap_checksum: str | None = None,
    score: int = 500_000,
    passed: bool = True,
    leaderboard_eligible_at_submission: bool = True,
    mods: ModCombination | None = None,
) -> Score:
    """再構築候補を表すtest用scoreを作成する.

    Args:
        score_id (int): scoreのIDとsubmitted_atのoffset.
        checksum (str): scoreのonline checksum.
        user_id (int): score所有userのID.
        beatmap_id (int): score対象beatmapのID.
        beatmap_checksum (str | None): 明示するbeatmap checksum. 未指定時はbeatmap IDから選ぶ.
        score (int): rank keyに使うscore値.
        passed (bool): scoreがpass済みか.
        leaderboard_eligible_at_submission (bool): submission時にleaderboard対象だったか.
        mods (ModCombination | None): scoreのmod組み合わせ. 未指定時はno-mod.

    Returns:
        Score: memory repositoryへ登録できるtest用score.
    """
    return Score(
        id=None,
        user_id=user_id,
        beatmap_id=beatmap_id,
        beatmap_checksum=beatmap_checksum or (_CHECKSUM_1 if beatmap_id == 1 else _CHECKSUM_2),
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
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
        leaderboard_eligible_at_submission=leaderboard_eligible_at_submission,
    )


def _beatmap(*, beatmap_id: int) -> Beatmap:
    """Beatmapset snapshotへ含めるtest用beatmapを作成する.

    Args:
        beatmap_id (int): 作成するbeatmapのID.

    Returns:
        Beatmap: rankedかつfile available状態のtest用beatmap.
    """
    checksum = _CHECKSUM_1 if beatmap_id == 1 else _CHECKSUM_2
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=10,
        checksum_md5=checksum,
        mode=BeatmapMode.OSU,
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

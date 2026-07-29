"""Beatmap Leaderboard command projection repositoryの契約を検証するtest."""

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
    """Isolated in-memory Unit of Work factoryを構築する.

    Returns:
        UnitOfWorkFactory: projection commit/rollbackを検証する新しいfactory.
    """
    return InMemoryUnitOfWorkFactory()


@pytest.mark.parametrize(
    "checksum",
    ["", "a" * 31, "a" * 33, "A" * 32, "g" * 32],
)
def test_user_scope_rejects_malformed_beatmap_checksum(checksum: str) -> None:
    """User best scopeが不正なMD5 checksumを境界で拒否する契約を検証する.

    空値と長さ違いと大文字または非16進数のchecksumでscopeを構築する.
    各入力でbeatmap_checksumを示すValueErrorが発生することを確認する.

    Args:
        checksum (str): 空値か形式不正なMD5 checksum.

    Returns:
        None: checksum validation contractを検証して完了する.
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
    """upsertが同一scopeの高順位candidateだけをuser bestへ置換する契約を検証する.

    作成済みbestより低順位と高順位のcandidateを同一scopeへ順にupsertする.
    低順位は既存rowを返し高順位だけがcommit後の保存rowになることを確認する.

    Returns:
        None: rank orderingによるuser best置換を検証して完了する.
    """
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
    """Checksum revisionが変わるcandidateをscore値にかかわらず置換する契約を検証する.

    同じbeatmap IDの古いchecksum rowと低いscoreを持つ新checksum rowをupsertする.
    古いrevisionが取得不能になり新revision rowだけが保存されることを確認する.

    Returns:
        None: stale revision置換とchecksum分離を検証して完了する.
    """
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
    """同scoreのuser bestがsubmission時刻とscore IDで決まる契約を検証する.

    同scoreのlater/earlier submissionと同時刻の異なるscore IDを同一scopeへupsertする.
    早いsubmissionを優先し同時刻では小さいscore IDを保持することを確認する.

    Returns:
        None: user best tie breakerの順序を検証して完了する.
    """
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
    """同じscore IDの反復upsertが一つのuser scope rowに収束する契約を検証する.

    同一scopeと同一rank keyを持つscoreを2回upsertしてcommitする.
    両操作が同じrowを返し保存結果も同じrowであることを確認する.

    Returns:
        None: score IDのidempotentなuser scope保存を検証して完了する.
    """
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
    """Raw Mod scopeごとのrowとmod横断global bestを両立する契約を検証する.

    NONEとHIDDENのscopeへ別scoreをupsertしてmodを含まないglobal scopeを取得する.
    各mod rowが独立して保存され最上位scoreがglobal bestになることを確認する.

    Returns:
        None: raw Mod分離とglobal best選択を検証して完了する.
    """
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
    """一つのscore IDを複数raw Mod scopeへ重複保存できない契約を検証する.

    NONE scopeへ保存済みのscore IDをHIDDEN scopeへ再度upsertする.
    projection rowの所有衝突を示すValueErrorが発生することを確認する.

    Returns:
        None: score IDのscope横断一意性を検証して完了する.
    """
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
    """空のuser projection sliceが対象userのstale rowだけを削除する契約を検証する.

    二人のuserにrowを保存して一人だけを対象に空rowでreplace projection sliceを行う.
    対象userのrowは削除され他userのrowは保存されたままであることを確認する.

    Returns:
        None: empty user sliceによる限定削除を検証して完了する.
    """
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
    """Beatmap projection sliceが対象beatmap IDだけを置換する契約を検証する.

    一人のuserに3 beatmapのrowを保存して2 IDを対象にreplacement rowを投入する.
    対象のstale rowが消えrebuilt rowへ置換され対象外rowは残ることを確認する.

    Returns:
        None: beatmap ID範囲に限定したprojection置換を検証して完了する.
    """
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
    """commit前のleaderboard projection rowがUnit of Work rollbackで破棄される契約を検証する.

    user bestをupsertしたtransactionでcommitせずrollbackを実行する.
    次のtransactionから対象scopeのrowが取得できないことを確認する.

    Returns:
        None: projection rowのtransaction rollback境界を検証して完了する.
    """
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
    """test用のraw Modを含むBeatmap Leaderboard user best scopeを構築する.

    Args:
        user_id (int): scoreを所有するuserのID.
        beatmap_id (int): leaderboard対象beatmapのID.
        beatmap_checksum (str | None): 使用するMD5 checksum. Noneならbeatmap ID由来の値.
        mods (Mod): raw Mod scopeに設定するMod bitflag.

    Returns:
        BeatmapLeaderboardUserBestScope: osu vanilla rulesetのuser best scope fixture.
    """
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
    """test用のraw Modを含まないBeatmap Leaderboard user scopeを構築する.

    Args:
        user_id (int): global bestを所有するuserのID.
        beatmap_id (int): leaderboard対象beatmapのID.
        beatmap_checksum (str | None): 使用するMD5 checksum. Noneならbeatmap ID由来の値.

    Returns:
        BeatmapLeaderboardUserScope: osu vanilla rulesetのmod横断scope fixture.
    """
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
    """testでupsertするBeatmap Leaderboard user best commandを構築する.

    Args:
        scope (BeatmapLeaderboardUserBestScope): commandを適用するraw Mod scope.
        score_id (int): projectionへ関連付けるscoreのID.
        score (int): rank keyへ設定するscore値.
        submitted_at (datetime): rank keyへ設定するsubmission timestamp.

    Returns:
        UpsertBeatmapLeaderboardUserBest: score rank keyを含むupsert command fixture.
    """
    return UpsertBeatmapLeaderboardUserBest(
        scope=scope,
        score_id=score_id,
        rank_key=ScoreRankKey(score=score, submitted_at=submitted_at, score_id=score_id),
    )

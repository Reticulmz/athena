"""メモリ上コマンドUnit of Workの可視性とrepository契約を検証する."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.memory.commands import (
    InMemoryBeatmapCommandRepository,
    InMemoryBeatmapLeaderboardCommandRepository,
    InMemoryBlobCommandRepository,
    InMemoryChannelCommandRepository,
    InMemoryChatCommandRepository,
    InMemoryFriendRelationshipCommandRepository,
    InMemoryPersonalBestCommandRepository,
    InMemoryReplayCommandRepository,
    InMemoryRoleCommandRepository,
    InMemoryScoreCommandRepository,
    InMemoryScorePerformanceCommandRepository,
    InMemoryScoreSubmissionCommandRepository,
    InMemoryUserCommandRepository,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from tests.factories.domain import make_channel, make_user

_NOW = datetime(2026, 6, 18, tzinfo=UTC)


async def test_commit_publishes_all_command_repository_changes() -> None:
    """コミット済みの複数repository変更が後続Unit of Workから読めることを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as uow:
        created_user = await uow.users.create(
            make_user(username="Commit User", email="commit@example.com")
        )
        created_channel = await uow.channels.create(make_channel(name="#commit"))
        await uow.commit()

    async with factory() as uow:
        assert await uow.users.get_by_safe_username("commit_user") == created_user
        assert await uow.channels.get_by_name("#commit") == created_channel


async def test_rollback_discards_multi_repository_command_changes() -> None:
    """ロールバックした複数repository変更が公開されないことを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as uow:
        _ = await uow.users.create(
            make_user(username="Rollback User", email="rollback@example.com")
        )
        _ = await uow.channels.create(make_channel(name="#rollback"))
        await uow.rollback()

    async with factory() as uow:
        assert await uow.users.get_by_safe_username("rollback_user") is None
        assert await uow.channels.get_by_name("#rollback") is None


async def test_exception_rolls_back_uncommitted_command_changes() -> None:
    """例外終了したUnit of Workの未コミット変更が破棄されることを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()

    with pytest.raises(RuntimeError, match="abort command"):
        await _raise_after_command_mutation(factory)

    async with factory() as uow:
        assert await uow.users.get_by_safe_username("exception_user") is None
        assert await uow.channels.get_by_name("#exception") is None


async def test_uncommitted_consistency_checks_are_scoped_to_active_unit_of_work() -> None:
    """未コミット変更が実行中Unit of Workだけに可視であることを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as command_uow:
        _ = await command_uow.users.create(
            make_user(username="Pending User", email="pending@example.com")
        )
        assert await command_uow.users.get_by_safe_username("pending_user") is not None

        async with factory() as observer_uow:
            assert await observer_uow.users.get_by_safe_username("pending_user") is None

        await command_uow.commit()

    async with factory() as observer_uow:
        assert await observer_uow.users.get_by_safe_username("pending_user") is not None


async def test_user_password_hash_update_commits_through_unit_of_work() -> None:
    """パスワードハッシュ更新がコミット後のUnit of Workへ反映されることを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as uow:
        created = await uow.users.create(
            make_user(username="Password User", email="password@example.com")
        )
        await uow.commit()

    async with factory() as uow:
        updated = await uow.users.update_password_hash(created.id, "new-hash")
        await uow.commit()

    async with factory() as uow:
        user = await uow.users.get_by_safe_username("password_user")

    assert updated is True
    assert user is not None
    assert user.password_hash == "new-hash"


async def test_role_assignment_replacement_commits_through_unit_of_work() -> None:
    """ロール置換がコミット後に置換後のロールだけを公開することを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    factory.seed_roles(
        [
            Role(id=1, name="Default", permissions=Privileges.NORMAL, position=0),
            Role(id=2, name="Moderator", permissions=Privileges.MODERATOR, position=10),
            Role(id=3, name="Admin", permissions=Privileges.ADMIN, position=20),
        ]
    )

    async with factory() as uow:
        await uow.roles.assign_role(user_id=42, role_id=1)
        await uow.roles.assign_role(user_id=42, role_id=2)
        await uow.roles.set_roles_for_user(user_id=42, role_ids=(3,))
        await uow.commit()

    async with factory() as uow:
        roles = await uow.roles.get_roles_for_user(42)

    assert [role.name for role in roles] == ["Admin"]


async def test_beatmap_leaderboard_projection_commit_publishes_through_unit_of_work() -> None:
    """リーダーボード投影のコミットが後続Unit of Workへ公開されることを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    scope = _leaderboard_scope()

    async with factory() as uow:
        created = await uow.beatmap_leaderboards.upsert_if_better(
            _leaderboard_upsert(scope=scope, score_id=90, score=1_000)
        )
        await uow.commit()

    async with factory() as uow:
        assert await uow.beatmap_leaderboards.get_user_best(scope) == created


async def test_beatmap_leaderboard_projection_rollback_discards_unit_of_work_changes() -> None:
    """リーダーボード投影のロールバックが後続Unit of Workへ公開されないことを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    scope = _leaderboard_scope()

    async with factory() as uow:
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _leaderboard_upsert(scope=scope, score_id=91, score=1_100)
        )
        await uow.rollback()

    async with factory() as uow:
        assert await uow.beatmap_leaderboards.get_user_best(scope) is None


async def test_unit_of_work_exposes_typed_command_repositories() -> None:
    """Unit of Workが各コマンドportに対応する具象repositoryを公開することを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()

    async with factory() as uow:
        assert isinstance(uow.users, InMemoryUserCommandRepository)
        assert isinstance(uow.roles, InMemoryRoleCommandRepository)
        assert isinstance(uow.channels, InMemoryChannelCommandRepository)
        assert isinstance(uow.chat, InMemoryChatCommandRepository)
        assert isinstance(uow.friends, InMemoryFriendRelationshipCommandRepository)
        assert isinstance(uow.scores, InMemoryScoreCommandRepository)
        assert isinstance(uow.personal_bests, InMemoryPersonalBestCommandRepository)
        assert isinstance(uow.submissions, InMemoryScoreSubmissionCommandRepository)
        assert isinstance(uow.replays, InMemoryReplayCommandRepository)
        assert isinstance(uow.blobs, InMemoryBlobCommandRepository)
        assert isinstance(uow.beatmaps, InMemoryBeatmapCommandRepository)
        assert isinstance(uow.beatmap_leaderboards, InMemoryBeatmapLeaderboardCommandRepository)
        assert isinstance(uow.score_performance, InMemoryScorePerformanceCommandRepository)


async def _raise_after_command_mutation(factory: InMemoryUnitOfWorkFactory) -> None:
    """変更後に例外を送出してコンテキスト終了時のロールバックを起動する.

    Args:
        factory (InMemoryUnitOfWorkFactory): 例外終了するUnit of Workを生成するfactory.

    Returns:
        None: 処理を完了し, 呼び出し側へ値を返さない.

    Raises:
        RuntimeError: 未コミット変更を中断するため常に送出する例外.
    """
    async with factory() as uow:
        _ = await uow.users.create(
            make_user(username="Exception User", email="exception@example.com")
        )
        _ = await uow.channels.create(make_channel(name="#exception"))
        raise RuntimeError("abort command")


def _leaderboard_scope() -> BeatmapLeaderboardUserBestScope:
    """リーダーボード投影テストで共有する検索スコープを生成する.

    Returns:
        BeatmapLeaderboardUserBestScope: 固定ユーザーとビートマップに限定したベストスコアスコープ.
    """
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=1,
        beatmap_checksum="a" * 32,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=2,
        mods=ModCombination.none(),
    )


def _leaderboard_upsert(
    *,
    scope: BeatmapLeaderboardUserBestScope,
    score_id: int,
    score: int,
) -> UpsertBeatmapLeaderboardUserBest:
    """リーダーボード投影を登録するコマンド入力を生成する.

    Args:
        scope (BeatmapLeaderboardUserBestScope): 登録先のユーザー別リーダーボードスコープ.
        score_id (int): 登録するスコアの識別子.
        score (int): ランク比較に使用するスコア値.

    Returns:
        UpsertBeatmapLeaderboardUserBest: 指定したランクキーを持つupsert入力.
    """
    return UpsertBeatmapLeaderboardUserBest(
        scope=scope,
        score_id=score_id,
        rank_key=ScoreRankKey(score=score, submitted_at=_NOW, score_id=score_id),
    )

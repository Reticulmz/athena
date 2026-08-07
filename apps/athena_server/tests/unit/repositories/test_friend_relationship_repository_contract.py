"""friend relationship repositoryのcommand/query contractを検証するtest module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.identity.users import User
from osu_server.repositories.memory.queries.friends import (
    InMemoryFriendRelationshipQueryRepository,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_NOW = datetime(2026, 6, 17, tzinfo=UTC)


@pytest.mark.asyncio
async def test_friend_relationship_add_remove_are_idempotent() -> None:
    """友人関係の追加と削除が冪等なcommand contractを検証する.

    同じowner/target組を2回追加してから2回削除し, 各操作が状態変更の有無をboolで返すことを確認する.

    Returns:
        None: command結果を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)

    async with factory() as uow:
        first_add = await uow.friends.add_relationship(owner_id, target_id)
        duplicate_add = await uow.friends.add_relationship(owner_id, target_id)
        first_remove = await uow.friends.remove_relationship(owner_id, target_id)
        missing_remove = await uow.friends.remove_relationship(owner_id, target_id)
        await uow.commit()

    assert first_add is True
    assert duplicate_add is False
    assert first_remove is True
    assert missing_remove is False


@pytest.mark.asyncio
async def test_friend_relationship_query_is_owner_scoped_and_one_way() -> None:
    """友人関係queryがowner単位かつ片方向のread contractを守ることを検証する.

    ownerからtargetへのrelationshipだけをcommitし, 両ownerからの一覧と存在照会が
    反転しないことを確認する.

    Returns:
        None: query結果を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)

    async with factory() as uow:
        _ = await uow.friends.add_relationship(owner_id, target_id)
        await uow.commit()

    repository = InMemoryFriendRelationshipQueryRepository(factory)

    assert await repository.list_friend_ids(owner_id) == (target_id,)
    assert await repository.list_friend_ids(target_id) == ()
    assert await repository.has_relationship(owner_id, target_id) is True
    assert await repository.has_relationship(target_id, owner_id) is False


@pytest.mark.asyncio
async def test_friend_relationships_participate_in_unit_of_work_commit_and_rollback() -> None:
    """友人関係がUnit of Workのcommit/rollback境界に従うことを検証する.

    commitしない追加はqueryから観測できず, commitした追加だけが永続stateとして
    観測できることを確認する.

    Returns:
        None: transaction境界を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)
    repository = InMemoryFriendRelationshipQueryRepository(factory)

    async with factory() as uow:
        _ = await uow.friends.add_relationship(owner_id, target_id)

    assert await repository.list_friend_ids(owner_id) == ()

    async with factory() as uow:
        _ = await uow.friends.add_relationship(owner_id, target_id)
        await uow.commit()

    assert await repository.list_friend_ids(owner_id) == (target_id,)


@pytest.mark.asyncio
async def test_friend_target_existence_uses_durable_users_not_sessions() -> None:
    """友人targetの存在確認がdurable user recordだけを基準にすることを検証する.

    sessionを作らずに作成済みuserを照会し, 未登録IDだけがFalseになることを確認する.

    Returns:
        None: target存在判定を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)

    async with factory() as uow:
        assert await uow.friends.target_exists(owner_id) is True
        assert await uow.friends.target_exists(target_id) is True
        assert await uow.friends.target_exists(999_999) is False


async def _create_users(factory: InMemoryUnitOfWorkFactory) -> tuple[int, int]:
    """友人関係test用のownerとtargetをdurable stateへ作成する.

    Args:
        factory (InMemoryUnitOfWorkFactory): user作成とcommitに使うUnit of Work factory.

    Returns:
        tuple[int, int]: commit済みowner IDとtarget IDの順序付き組.
    """
    async with factory() as uow:
        owner = await uow.users.create(_user(username="Owner"))
        target = await uow.users.create(_user(username="Target"))
        await uow.commit()
    return owner.id, target.id


def _user(*, username: str) -> User:
    """友人関係testで使う最低限のUserを組み立てる.

    Args:
        username (str): safe usernameとemailの元になる表示名.

    Returns:
        User: 固定時刻と正規化済みusernameを持つ未永続化user.
    """
    safe_username = User.normalize_username(username)
    return User(
        id=0,
        username=username,
        safe_username=safe_username,
        email=f"{safe_username}@example.com",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )

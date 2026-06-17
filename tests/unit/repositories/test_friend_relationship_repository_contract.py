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
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)

    async with factory() as uow:
        assert await uow.friends.target_exists(owner_id) is True
        assert await uow.friends.target_exists(target_id) is True
        assert await uow.friends.target_exists(999_999) is False


async def _create_users(factory: InMemoryUnitOfWorkFactory) -> tuple[int, int]:
    async with factory() as uow:
        owner = await uow.users.create(_user(username="Owner"))
        target = await uow.users.create(_user(username="Target"))
        await uow.commit()
    return owner.id, target.id


def _user(*, username: str) -> User:
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

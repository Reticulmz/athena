from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.identity.friends import (
    FriendableSystemUserCatalog,
    FriendMutationStatus,
)
from osu_server.domain.identity.system_users import (
    BANCHO_BOT_IDENTITY,
    SystemUserIdentity,
)
from osu_server.domain.identity.users import User
from osu_server.repositories.memory.queries.friends import (
    InMemoryFriendRelationshipQueryRepository,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.identity.friend_relationships import (
    AddFriendCommand,
    AddFriendUseCase,
    RemoveFriendCommand,
    RemoveFriendUseCase,
)
from osu_server.services.queries.identity.friend_relationships import (
    CheckFriendRelationshipQuery,
    GetFriendEligibleUserIdsQuery,
    ListFriendIdsQuery,
    ListFriendIdsQueryInput,
)

_NOW = datetime(2026, 6, 17, tzinfo=UTC)


@pytest.mark.asyncio
async def test_add_friend_creates_one_way_relationship_for_existing_offline_target() -> None:
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)
    use_case = _add_use_case(factory)

    result = await use_case.execute(
        AddFriendCommand(owner_user_id=owner_id, target_user_id=target_id)
    )
    query = InMemoryFriendRelationshipQueryRepository(factory)

    assert result.status is FriendMutationStatus.ADDED
    assert await query.list_friend_ids(owner_id) == (target_id,)
    assert await query.list_friend_ids(target_id) == ()


@pytest.mark.asyncio
async def test_add_friend_no_ops_for_unknown_self_and_duplicate_targets() -> None:
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)
    use_case = _add_use_case(factory)

    unknown = await use_case.execute(
        AddFriendCommand(owner_user_id=owner_id, target_user_id=999_999)
    )
    self_target = await use_case.execute(
        AddFriendCommand(owner_user_id=owner_id, target_user_id=owner_id)
    )
    added = await use_case.execute(
        AddFriendCommand(owner_user_id=owner_id, target_user_id=target_id)
    )
    duplicate = await use_case.execute(
        AddFriendCommand(owner_user_id=owner_id, target_user_id=target_id)
    )

    assert unknown.status is FriendMutationStatus.NO_OP
    assert self_target.status is FriendMutationStatus.NO_OP
    assert added.status is FriendMutationStatus.ADDED
    assert duplicate.status is FriendMutationStatus.NO_OP


@pytest.mark.asyncio
async def test_remove_friend_removes_existing_relationship_and_no_ops_missing() -> None:
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)
    add_use_case = _add_use_case(factory)
    remove_use_case = RemoveFriendUseCase(uow_factory=factory)

    _ = await add_use_case.execute(
        AddFriendCommand(owner_user_id=owner_id, target_user_id=target_id)
    )
    removed = await remove_use_case.execute(
        RemoveFriendCommand(owner_user_id=owner_id, target_user_id=target_id)
    )
    missing = await remove_use_case.execute(
        RemoveFriendCommand(owner_user_id=owner_id, target_user_id=target_id)
    )

    assert removed.status is FriendMutationStatus.REMOVED
    assert missing.status is FriendMutationStatus.NO_OP


@pytest.mark.asyncio
async def test_banchobot_is_explicitly_friendable_but_nonfriendable_system_user_is_not() -> None:
    factory = InMemoryUnitOfWorkFactory()
    owner_id, _ = await _create_users(factory)
    async with factory() as uow:
        await uow.users.sync_system_user(BANCHO_BOT_IDENTITY)
        nonfriendable = await uow.users.create(_user(username="System99"))
        await uow.commit()

    add_banchobot = _add_use_case(factory)
    add_nonfriendable = _add_use_case(
        factory,
        catalog=FriendableSystemUserCatalog(
            system_users=(SystemUserIdentity(user_id=nonfriendable.id, username="System99"),),
            friendable_user_ids=frozenset(),
        ),
    )

    banchobot_result = await add_banchobot.execute(
        AddFriendCommand(
            owner_user_id=owner_id,
            target_user_id=BANCHO_BOT_IDENTITY.user_id,
        )
    )
    nonfriendable_result = await add_nonfriendable.execute(
        AddFriendCommand(owner_user_id=owner_id, target_user_id=nonfriendable.id)
    )

    assert banchobot_result.status is FriendMutationStatus.ADDED
    assert nonfriendable_result.status is FriendMutationStatus.NO_OP


@pytest.mark.asyncio
async def test_friend_queries_share_owner_scoped_source_of_truth() -> None:
    factory = InMemoryUnitOfWorkFactory()
    owner_id, target_id = await _create_users(factory)
    _ = await _add_use_case(factory).execute(
        AddFriendCommand(owner_user_id=owner_id, target_user_id=target_id)
    )
    repository = InMemoryFriendRelationshipQueryRepository(factory)

    list_query = ListFriendIdsQuery(repository=repository)
    check_query = CheckFriendRelationshipQuery(repository=repository)
    eligible_query = GetFriendEligibleUserIdsQuery(repository=repository)

    listed = await list_query.execute(ListFriendIdsQueryInput(owner_user_id=owner_id))
    has_forward = await check_query.execute(owner_user_id=owner_id, target_user_id=target_id)
    has_reverse = await check_query.execute(owner_user_id=target_id, target_user_id=owner_id)
    eligible = await eligible_query.execute(viewer_user_id=owner_id)

    assert listed.friend_user_ids == (target_id,)
    assert has_forward is True
    assert has_reverse is False
    assert eligible == (target_id,)


def _add_use_case(
    factory: InMemoryUnitOfWorkFactory,
    *,
    catalog: FriendableSystemUserCatalog | None = None,
) -> AddFriendUseCase:
    return AddFriendUseCase(
        uow_factory=factory,
        system_user_catalog=catalog or FriendableSystemUserCatalog.with_bancho_bot(),
    )


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

"""Channel command/query use-case boundary tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.domain.identity.authorization import Privileges
from osu_server.infrastructure.state.memory.channel_state_store import (
    InMemoryChannelStateStore,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.chat import (
    JoinChannelCommand,
    JoinChannelUseCase,
    LeaveChannelCommand,
    LeaveChannelUseCase,
)
from osu_server.services.queries.chat import (
    ChannelCatalogQueryInput,
    ListAutojoinChannelsQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
    ResolveChannelMessageDeliveryQueryInput,
)

_NOW = datetime(2025, 1, 1, tzinfo=UTC)
_USER_ID = 100
_TARGET_ID = 200
_DEFAULT_ROLE_ID = 1
_NORMAL_PRIVILEGES = int(Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED)
_BYPASS_PRIVILEGES = int(Privileges.NORMAL | Privileges.BYPASS_CHANNEL_ACL)


@dataclass(frozen=True, slots=True)
class ChannelUseCaseRuntime:
    """In-memory runtime dependencies for channel use-case tests."""

    command_state: InMemoryCommandRepositoryState
    uow_factory: InMemoryUnitOfWorkFactory
    channel_repository: InMemoryChannelQueryRepository
    channel_state: InMemoryChannelStateStore


def _make_runtime() -> ChannelUseCaseRuntime:
    command_state = InMemoryCommandRepositoryState()
    uow_factory = InMemoryUnitOfWorkFactory(command_state)
    return ChannelUseCaseRuntime(
        command_state=command_state,
        uow_factory=uow_factory,
        channel_repository=InMemoryChannelQueryRepository(uow_factory),
        channel_state=InMemoryChannelStateStore(),
    )


def _make_channel(
    *,
    name: str = "#osu",
    topic: str = "General discussion",
    auto_join: bool = False,
) -> Channel:
    return Channel(
        id=0,
        name=name,
        topic=topic,
        channel_type=ChannelType.PUBLIC,
        auto_join=auto_join,
        rate_limit_messages=None,
        rate_limit_window=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


async def _seed_channel(
    runtime: ChannelUseCaseRuntime,
    *,
    name: str = "#osu",
    auto_join: bool = False,
    overrides: tuple[tuple[int, bool, bool], ...] = ((_DEFAULT_ROLE_ID, True, True),),
) -> Channel:
    async with runtime.uow_factory() as uow:
        channel = await uow.channels.create(_make_channel(name=name, auto_join=auto_join))
        await uow.commit()

    runtime.command_state.channel_overrides_by_channel_id[channel.id] = [
        ChannelRoleOverride(
            channel_id=channel.id,
            role_id=role_id,
            can_read=can_read,
            can_write=can_write,
        )
        for role_id, can_read, can_write in overrides
    ]
    return channel


def _join_use_case(runtime: ChannelUseCaseRuntime) -> JoinChannelUseCase:
    return JoinChannelUseCase(
        channel_repository=runtime.channel_repository,
        channel_state=runtime.channel_state,
    )


def _leave_use_case(runtime: ChannelUseCaseRuntime) -> LeaveChannelUseCase:
    return LeaveChannelUseCase(channel_state=runtime.channel_state)


def _visible_channels_query(runtime: ChannelUseCaseRuntime) -> ListVisibleChannelsQuery:
    return ListVisibleChannelsQuery(
        channel_repository=runtime.channel_repository,
        channel_state=runtime.channel_state,
    )


def _autojoin_channels_query(runtime: ChannelUseCaseRuntime) -> ListAutojoinChannelsQuery:
    return ListAutojoinChannelsQuery(
        channel_repository=runtime.channel_repository,
        channel_state=runtime.channel_state,
    )


def _delivery_query(runtime: ChannelUseCaseRuntime) -> ResolveChannelMessageDeliveryQuery:
    return ResolveChannelMessageDeliveryQuery(
        channel_repository=runtime.channel_repository,
        channel_state=runtime.channel_state,
    )


async def test_join_channel_use_case_adds_member_when_acl_allows() -> None:
    runtime = _make_runtime()
    _ = await _seed_channel(runtime)

    result = await _join_use_case(runtime).execute(
        JoinChannelCommand(
            user_id=_USER_ID,
            channel_name="#osu",
            user_privileges=_NORMAL_PRIVILEGES,
            user_role_ids=(_DEFAULT_ROLE_ID,),
        )
    )

    assert result.joined is True
    assert await runtime.channel_state.is_member("#osu", _USER_ID)


async def test_join_channel_use_case_rejects_without_read_acl() -> None:
    runtime = _make_runtime()
    _ = await _seed_channel(runtime, overrides=((_DEFAULT_ROLE_ID, False, True),))

    result = await _join_use_case(runtime).execute(
        JoinChannelCommand(
            user_id=_USER_ID,
            channel_name="#osu",
            user_privileges=_NORMAL_PRIVILEGES,
            user_role_ids=(_DEFAULT_ROLE_ID,),
        )
    )

    assert result.joined is False
    assert not await runtime.channel_state.is_member("#osu", _USER_ID)


async def test_join_channel_use_case_allows_bypass_privilege() -> None:
    runtime = _make_runtime()
    _ = await _seed_channel(runtime, overrides=())

    result = await _join_use_case(runtime).execute(
        JoinChannelCommand(
            user_id=_USER_ID,
            channel_name="#osu",
            user_privileges=_BYPASS_PRIVILEGES,
            user_role_ids=(),
        )
    )

    assert result.joined is True
    assert await runtime.channel_state.is_member("#osu", _USER_ID)


async def test_leave_channel_use_case_removes_member() -> None:
    runtime = _make_runtime()
    _ = await _seed_channel(runtime)
    await runtime.channel_state.add_member("#osu", _USER_ID)

    await _leave_use_case(runtime).execute(
        LeaveChannelCommand(user_id=_USER_ID, channel_name="#osu")
    )

    assert not await runtime.channel_state.is_member("#osu", _USER_ID)


async def test_resolve_channel_message_delivery_returns_targets() -> None:
    runtime = _make_runtime()
    _ = await _seed_channel(runtime)
    await runtime.channel_state.add_member("#osu", _USER_ID)
    await runtime.channel_state.add_member("#osu", _TARGET_ID)

    result = await _delivery_query(runtime).execute(
        ResolveChannelMessageDeliveryQueryInput(
            sender_id=_USER_ID,
            channel_name="#osu",
            user_privileges=_NORMAL_PRIVILEGES,
            user_role_ids=(_DEFAULT_ROLE_ID,),
        )
    )

    assert result.channel is not None
    assert result.delivered_to == frozenset({_TARGET_ID})


async def test_resolve_channel_message_delivery_rejects_non_member() -> None:
    runtime = _make_runtime()
    _ = await _seed_channel(runtime)

    result = await _delivery_query(runtime).execute(
        ResolveChannelMessageDeliveryQueryInput(
            sender_id=_USER_ID,
            channel_name="#osu",
            user_privileges=_NORMAL_PRIVILEGES,
            user_role_ids=(_DEFAULT_ROLE_ID,),
        )
    )

    assert result.channel is None
    assert result.delivered_to is None


async def test_channel_catalog_queries_filter_visible_and_autojoin_channels() -> None:
    runtime = _make_runtime()
    _ = await _seed_channel(
        runtime,
        name="#osu",
        auto_join=True,
        overrides=((_DEFAULT_ROLE_ID, True, True),),
    )
    _ = await _seed_channel(
        runtime,
        name="#staff",
        auto_join=True,
        overrides=((999, True, True),),
    )
    await runtime.channel_state.add_member("#osu", _USER_ID)
    await runtime.channel_state.add_member("#osu", _TARGET_ID)

    input_data = ChannelCatalogQueryInput(
        user_privileges=_NORMAL_PRIVILEGES,
        user_role_ids=(_DEFAULT_ROLE_ID,),
    )

    visible = await _visible_channels_query(runtime).execute(input_data)
    autojoin = await _autojoin_channels_query(runtime).execute(input_data)

    assert [(channel.name, count) for channel, count in visible.channels] == [("#osu", 2)]
    assert [(channel.name, count) for channel, count in autojoin.channels] == [("#osu", 2)]

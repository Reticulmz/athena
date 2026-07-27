"""チャネル command/query use-case の境界契約を検証するテスト.

in-memory 実装を使い, ACL とメンバー状態が command/query 結果へ反映されることを検証する.
"""

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
    """チャネル use-case テスト用の in-memory 依存をまとめる値.

    Attributes:
        command_state (InMemoryCommandRepositoryState): チャネルと role override の永続化状態.
        uow_factory (InMemoryUnitOfWorkFactory): command state を共有する unit of work factory.
        channel_repository (InMemoryChannelQueryRepository): チャネル表示用の query repository.
        channel_state (InMemoryChannelStateStore): チャネルメンバーシップを保持する volatile state.
    """

    command_state: InMemoryCommandRepositoryState
    uow_factory: InMemoryUnitOfWorkFactory
    channel_repository: InMemoryChannelQueryRepository
    channel_state: InMemoryChannelStateStore


def _make_runtime() -> ChannelUseCaseRuntime:
    """独立したチャネル use-case 実行環境を構築する.

    Returns:
        ChannelUseCaseRuntime: command/query repository と state store を共有する runtime.
    """
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
    """テスト用の public channel を生成する.

    Args:
        name (str): 作成するチャネル名.
        topic (str): チャネル topic.
        auto_join (bool): login 時に自動参加させるかどうか.

    Returns:
        Channel: 未永続化の public channel.
    """
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
    """Runtime へチャネルと ACL override を永続化する.

    Args:
        runtime (ChannelUseCaseRuntime): チャネルを登録する in-memory runtime.
        name (str): 登録するチャネル名.
        auto_join (bool): 自動参加対象にするかどうか.
        overrides (tuple[tuple[int, bool, bool], ...]): role ID と read/write 許可の組.

    Returns:
        Channel: 永続化され role override を設定したチャネル.

    Constraints:
        override は command state を直接更新し, repository の公開 API では設定しない.
    """
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
    """指定 runtime 用の join channel command を構築する.

    Args:
        runtime (ChannelUseCaseRuntime): 依存を提供する in-memory runtime.

    Returns:
        JoinChannelUseCase: channel repository と state store を使う command.
    """
    return JoinChannelUseCase(
        channel_repository=runtime.channel_repository,
        channel_state=runtime.channel_state,
    )


def _leave_use_case(runtime: ChannelUseCaseRuntime) -> LeaveChannelUseCase:
    """指定 runtime 用の leave channel command を構築する.

    Args:
        runtime (ChannelUseCaseRuntime): state store を提供する in-memory runtime.

    Returns:
        LeaveChannelUseCase: member state を削除する command.
    """
    return LeaveChannelUseCase(channel_state=runtime.channel_state)


def _visible_channels_query(runtime: ChannelUseCaseRuntime) -> ListVisibleChannelsQuery:
    """指定 runtime 用の visible channel query を構築する.

    Args:
        runtime (ChannelUseCaseRuntime): query repository と state store を提供する runtime.

    Returns:
        ListVisibleChannelsQuery: ACL で可視なチャネルを返す query.
    """
    return ListVisibleChannelsQuery(
        channel_repository=runtime.channel_repository,
        channel_state=runtime.channel_state,
    )


def _autojoin_channels_query(runtime: ChannelUseCaseRuntime) -> ListAutojoinChannelsQuery:
    """指定 runtime 用の autojoin channel query を構築する.

    Args:
        runtime (ChannelUseCaseRuntime): query repository と state store を提供する runtime.

    Returns:
        ListAutojoinChannelsQuery: 自動参加対象の可視チャネルを返す query.
    """
    return ListAutojoinChannelsQuery(
        channel_repository=runtime.channel_repository,
        channel_state=runtime.channel_state,
    )


def _delivery_query(runtime: ChannelUseCaseRuntime) -> ResolveChannelMessageDeliveryQuery:
    """指定 runtime 用のチャネル配信先 query を構築する.

    Args:
        runtime (ChannelUseCaseRuntime): query repository と state store を提供する runtime.

    Returns:
        ResolveChannelMessageDeliveryQuery: sender の配信先 member を解決する query.
    """
    return ResolveChannelMessageDeliveryQuery(
        channel_repository=runtime.channel_repository,
        channel_state=runtime.channel_state,
    )


async def test_join_channel_use_case_adds_member_when_acl_allows() -> None:
    """Read ACL を満たす user がチャネル member として追加されることを検証する.

    Returns:
        None: join 結果と state store の member 状態を検証して完了する.
    """
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
    """Read ACL がない user の join を拒否することを検証する.

    Returns:
        None: join 失敗と member 非追加を検証して完了する.
    """
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
    """BYPASS_CHANNEL_ACL 権限が role override なしでも join を許可することを検証する.

    Returns:
        None: join 成功と member 追加を検証して完了する.
    """
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
    """Leave command が既存 member を state store から削除することを検証する.

    Returns:
        None: leave 後に member ではないことを検証して完了する.
    """
    runtime = _make_runtime()
    _ = await _seed_channel(runtime)
    await runtime.channel_state.add_member("#osu", _USER_ID)

    await _leave_use_case(runtime).execute(
        LeaveChannelCommand(user_id=_USER_ID, channel_name="#osu")
    )

    assert not await runtime.channel_state.is_member("#osu", _USER_ID)


async def test_resolve_channel_message_delivery_returns_targets() -> None:
    """Member sender の message 配信先が他 member だけになることを検証する.

    Returns:
        None: channel と target ID 集合を検証して完了する.
    """
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
    """チャネル非 member の message 配信先を解決しないことを検証する.

    Returns:
        None: channel と delivery target が None であることを検証して完了する.
    """
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
    """visible/autojoin query が ACL と member 数でチャネルを絞ることを検証する.

    Returns:
        None: 許可 role に対応する autojoin channel だけを検証して完了する.
    """
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

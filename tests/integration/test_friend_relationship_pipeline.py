"""friend relationshipとlogin rosterの統合契約を検証する.

stable C2S friend操作をin-memory persistenceへ接続する.
login responseのFRIENDS_LISTとonline presenceへの反映を確認する.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from caterpillar.model import unpack

from osu_server.domain.identity.authentication import LoginResponse
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.friends import FriendableSystemUserCatalog
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.commands.users import InMemoryUserCommandRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.friends import (
    InMemoryFriendRelationshipQueryRepository,
)
from osu_server.repositories.memory.queries.user_stats import InMemoryUserStatsQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.identity import (
    AddFriendUseCase,
    RemoveFriendUseCase,
    UpdateFriendOnlyDmUseCase,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListVisibleChannelsQuery,
)
from osu_server.services.queries.identity.friend_relationships import ListFriendIdsQuery
from osu_server.services.queries.identity.online_sessions import ListActiveSessionsQueryUseCase
from osu_server.services.queries.scores import CurrentUserStatsQuery
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.friends import FriendHandlers
from osu_server.transports.stable.bancho.protocol.c2s import friend_user_id_payload
from osu_server.transports.stable.bancho.protocol.enums import (
    ClientPacketID,
    ServerPacketID,
)
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    user_presence,
    user_presence_bundle,
)
from osu_server.transports.stable.bancho.protocol.types import IntList
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from tests.factories.domain import make_user

if TYPE_CHECKING:
    from osu_server.domain.identity.users import User

_HEADER = struct.Struct("<HBI")


@dataclass(slots=True)
class FriendPipeline:
    """friend integration testで共有する構成済みcomponentを保持する.

    Attributes:
        dispatcher (PacketDispatcher): friend関連C2S packetをhandlerへ配送するdispatcher.
        login_response_builder (LoginResponseBuilder): login packet streamを構築するworkflow.
        session_store (InMemorySessionStore): online利用者の接続状態を保持するstore.
        owner (User): friend relationshipを所有するtest利用者.
        target (User): ownerがfriend追加または削除するtest利用者.
    """

    dispatcher: PacketDispatcher
    login_response_builder: LoginResponseBuilder
    session_store: InMemorySessionStore
    owner: User
    target: User


async def _setup_pipeline() -> FriendPipeline:
    """Friend handlerとlogin response builderを持つin-memory pipelineを構築する.

    Returns:
        FriendPipeline: ownerとtargetとfriend C2S handlerを登録済みの構成.

    Notes:
        BanchoBotはfriend候補として扱えるsystem userとして事前同期する.
    """
    command_state = InMemoryCommandRepositoryState()
    uow_factory = InMemoryUnitOfWorkFactory(command_state)
    user_repo = InMemoryUserCommandRepository(command_state)
    await user_repo.sync_system_user(BANCHO_BOT_IDENTITY)
    owner = await user_repo.create(make_user(username="Owner", email="owner@example.com"))
    target = await user_repo.create(make_user(username="Target", email="target@example.com"))

    dispatcher = PacketDispatcher()
    session_store = InMemorySessionStore()
    friend_handlers = FriendHandlers(
        add_friend=AddFriendUseCase(
            uow_factory=uow_factory,
            system_user_catalog=FriendableSystemUserCatalog.with_bancho_bot(),
        ),
        remove_friend=RemoveFriendUseCase(uow_factory=uow_factory),
        update_friend_only_dm=UpdateFriendOnlyDmUseCase(session_store=session_store),
    )
    friend_handlers.register_all(dispatcher)

    channel_state = InMemoryChannelStateStore()
    channel_repository = InMemoryChannelQueryRepository(uow_factory)
    friend_query_repository = InMemoryFriendRelationshipQueryRepository(uow_factory)
    stats_query_repository = InMemoryUserStatsQueryRepository(uow_factory)
    login_response_builder = LoginResponseBuilder(
        visible_channels_query=ListVisibleChannelsQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        ),
        autojoin_channels_query=ListAutojoinChannelsQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        ),
        friend_ids_query=ListFriendIdsQuery(repository=friend_query_repository),
        active_sessions_query=ListActiveSessionsQueryUseCase(session_store=session_store),
        current_user_stats_query=CurrentUserStatsQuery(repository=stats_query_repository),
    )
    return FriendPipeline(
        dispatcher=dispatcher,
        login_response_builder=login_response_builder,
        session_store=session_store,
        owner=owner,
        target=target,
    )


def _login_response(user: User) -> LoginResponse:
    """指定利用者のlogin responseをテスト用に構築する.

    Args:
        user (User): loginを完了したものとして扱う利用者.

    Returns:
        LoginResponse: normalかつverified権限と固定session dataを持つresponse.
    """
    privileges = Privileges.NORMAL | Privileges.VERIFIED
    return LoginResponse(
        token="test-token",
        user=user,
        privileges=privileges,
        role_ids=(),
        country=user.country,
        session_data=SessionData(
            user_id=user.id,
            username=user.username,
            privileges=int(privileges),
            country=user.country,
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        ),
    )


def _friend_ids_from_login_stream(stream: bytes) -> frozenset[int]:
    """Login packet streamからFRIENDS_LISTの利用者ID集合を抽出する.

    Args:
        stream (bytes): LoginResponseBuilderが構築したS2C packet stream.

    Returns:
        frozenset[int]: FRIENDS_LIST packetに含まれるfriend利用者IDの重複なし集合.

    Raises:
        AssertionError: streamにFRIENDS_LIST packetが含まれない場合.
    """
    offset = 0
    while offset < len(stream):
        packet_id, _compressed, payload_size = cast(
            "tuple[int, int, int]",
            _HEADER.unpack(stream[offset : offset + 7]),
        )
        payload_start = offset + 7
        payload = stream[payload_start : payload_start + payload_size]
        if packet_id == ServerPacketID.FRIENDS_LIST:
            int_list = unpack(IntList, payload)
            return frozenset(int_list.values)
        offset = payload_start + payload_size
    msg = "FRIENDS_LIST packet missing from login stream"
    raise AssertionError(msg)


async def _build_friend_ids(pipeline: FriendPipeline) -> frozenset[int]:
    """ownerのlogin responseからfriend利用者ID集合を取得する.

    Args:
        pipeline (FriendPipeline): ownerとlogin response builderを持つtest構成.

    Returns:
        frozenset[int]: ownerのFRIENDS_LISTに含まれるfriend利用者ID集合.

    Raises:
        AssertionError: login packet streamにFRIENDS_LISTが存在しない場合.
    """
    stream = await pipeline.login_response_builder.build(_login_response(pipeline.owner))
    return _friend_ids_from_login_stream(stream)


async def test_stable_add_remove_friend_updates_login_friends_list() -> None:
    """Stable ADD_FRIENDとREMOVE_FRIENDが次のlogin FRIENDS_LISTへ反映されることを検証する.

    ownerからtargetへのfriend関係を追加してから削除する.
    観測結果としてlogin streamのfriend ID集合は空からtargetのみを経て再び空になる.

    Returns:
        None: C2S mutationとlogin projectionの整合を検証して終了する.
    """
    pipeline = await _setup_pipeline()

    assert await _build_friend_ids(pipeline) == frozenset()

    await pipeline.dispatcher.dispatch(
        ClientPacketID.ADD_FRIEND,
        friend_user_id_payload(pipeline.target.id),
        pipeline.owner.id,
    )

    assert await _build_friend_ids(pipeline) == frozenset({pipeline.target.id})

    await pipeline.dispatcher.dispatch(
        ClientPacketID.REMOVE_FRIEND,
        friend_user_id_payload(pipeline.target.id),
        pipeline.owner.id,
    )

    assert await _build_friend_ids(pipeline) == frozenset()


async def test_login_friends_list_includes_offline_and_explicit_banchobot_only() -> None:
    """Login FRIENDS_LISTがoffline friendと明示追加したBanchoBotだけを含むことを検証する.

    targetからownerへの片方向friendを先に追加してownerのlogin結果を確認する.
    次にownerからtargetとBanchoBotを追加し観測結果として両者だけがfriend集合に含まれる.

    Returns:
        None: relationship方向とsystem userのfriend projectionを検証して終了する.
    """
    pipeline = await _setup_pipeline()

    await pipeline.dispatcher.dispatch(
        ClientPacketID.ADD_FRIEND,
        friend_user_id_payload(pipeline.owner.id),
        pipeline.target.id,
    )

    assert await _build_friend_ids(pipeline) == frozenset()

    await pipeline.dispatcher.dispatch(
        ClientPacketID.ADD_FRIEND,
        friend_user_id_payload(pipeline.target.id),
        pipeline.owner.id,
    )
    await pipeline.dispatcher.dispatch(
        ClientPacketID.ADD_FRIEND,
        friend_user_id_payload(BANCHO_BOT_IDENTITY.user_id),
        pipeline.owner.id,
    )

    assert await _build_friend_ids(pipeline) == frozenset(
        {pipeline.target.id, BANCHO_BOT_IDENTITY.user_id}
    )


async def test_login_presence_includes_active_online_user_sessions() -> None:
    """Login responseがactive sessionを持つ利用者のpresenceとroster IDを含むことを検証する.

    targetのsessionを作成してownerのlogin responseを構築する.
    観測結果としてtargetのUSER_PRESENCEとBanchoBotと両利用者のbundleがstreamに含まれる.

    Returns:
        None: online sessionからlogin rosterを構築する契約を検証して終了する.
    """
    pipeline = await _setup_pipeline()
    privileges = Privileges.NORMAL | Privileges.VERIFIED
    await pipeline.session_store.create(
        user_id=pipeline.target.id,
        token="target-token",
        data=SessionData(
            user_id=pipeline.target.id,
            username=pipeline.target.username,
            privileges=int(privileges),
            country=pipeline.target.country,
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        ),
    )

    stream = await pipeline.login_response_builder.build(_login_response(pipeline.owner))

    assert (
        user_presence(
            user_id=pipeline.target.id,
            username=pipeline.target.username,
            timezone=33,
            country_id=country_code_to_id(pipeline.target.country),
            permissions=1,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
        in stream
    )
    assert (
        user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, pipeline.owner.id, pipeline.target.id])
        in stream
    )

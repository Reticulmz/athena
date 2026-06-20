from __future__ import annotations

import random
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from caterpillar.model import pack
from pydantic import PostgresDsn, RedisDsn

from osu_server.config import AppConfig
from osu_server.domain.events.users import UserDisconnected
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.friends import FriendableSystemUserCatalog
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.messaging.memory import InMemoryLocalEventBus
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.jobs.chat_persistence_publisher import TaskiqChatPersistenceWorkPublisher
from osu_server.repositories.memory.commands.channels import InMemoryChannelCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.commands.users import InMemoryUserCommandRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.friends import (
    InMemoryFriendRelationshipQueryRepository,
)
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
from osu_server.services.commands.chat.bancho_bot.commands import create_builtin_registry
from osu_server.services.commands.identity import (
    AddFriendUseCase,
    RemoveFriendUseCase,
    UpdateFriendOnlyDmUseCase,
)
from osu_server.services.queries.chat import (
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
)
from osu_server.services.queries.identity.friend_relationships import CheckFriendRelationshipQuery
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.chat import ChatHandlers
from osu_server.transports.stable.bancho.handlers.friends import FriendHandlers
from osu_server.transports.stable.bancho.listeners.chat import ChatListeners
from osu_server.transports.stable.bancho.protocol.c2s import (
    message_payload as c2s_message_payload,
)
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.s2c.chat import (
    channel_join_success,
    send_message,
    user_dm_blocked,
)
from osu_server.transports.stable.bancho.protocol.types import BanchoString
from tests.factories.domain import make_channel, make_user

if TYPE_CHECKING:
    import pytest
    from taskiq import AsyncBroker


class SpyTask:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def kiq(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


class SpyBroker:
    def __init__(self) -> None:
        self.tasks: dict[str, SpyTask] = {}

    def find_task(self, name: str) -> SpyTask:
        task = self.tasks.get(name)
        if task is None:
            task = SpyTask()
            self.tasks[name] = task
        return task


@dataclass(slots=True)
class ChatPipeline:
    dispatcher: PacketDispatcher
    packet_queue: InMemoryPacketQueue
    channel_state: InMemoryChannelStateStore
    broker: SpyBroker
    sender_id: int
    target_id: int
    offline_id: int


def _session(user_id: int, username: str) -> SessionData:
    return SessionData(
        user_id=user_id,
        username=username,
        privileges=int(Privileges.BYPASS_CHANNEL_ACL),
        country="JP",
        osu_version="test",
        utc_offset=9,
        display_city=False,
        client_hashes="",
        pm_private=False,
    )


def _message_payload(*, content: str, target: str) -> bytes:
    return c2s_message_payload(sender="", content=content, target=target, sender_id=0)


def _channel_payload(channel_name: str) -> bytes:
    return pack(channel_name, BanchoString)


async def _setup_pipeline() -> ChatPipeline:
    command_state = InMemoryCommandRepositoryState()
    uow_factory = InMemoryUnitOfWorkFactory(command_state)
    user_repo = InMemoryUserCommandRepository(command_state)
    session_store = InMemorySessionStore()
    channel_repo = InMemoryChannelCommandRepository(command_state)
    user_query_repo = InMemoryUserQueryRepository(uow_factory)
    channel_query_repo = InMemoryChannelQueryRepository(uow_factory)
    channel_state = InMemoryChannelStateStore()
    packet_queue = InMemoryPacketQueue()
    broker = SpyBroker()
    persistence_publisher = TaskiqChatPersistenceWorkPublisher(
        cast("AsyncBroker", cast("object", broker))
    )

    await user_repo.sync_system_user(BANCHO_BOT_IDENTITY)
    sender = await user_repo.create(make_user(username="Sender", email="sender@example.com"))
    target = await user_repo.create(make_user(username="Target", email="target@example.com"))
    offline = await user_repo.create(make_user(username="Offline", email="offline@example.com"))

    await session_store.create(sender.id, "sender-token", _session(sender.id, sender.username))
    await session_store.create(target.id, "target-token", _session(target.id, target.username))

    for user_id in (sender.id, target.id, offline.id):
        await packet_queue.refresh_ttl(user_id, ttl=300)

    _ = await channel_repo.create(make_channel(name="#osu", auto_join=False))
    await channel_state.add_member("#osu", target.id)

    channel_delivery_query = ResolveChannelMessageDeliveryQuery(
        channel_repository=channel_query_repo,
        channel_state=channel_state,
    )
    private_message_target_query = ResolvePrivateMessageTargetQuery(
        user_repository=user_query_repo,
        session_store=session_store,
    )
    friend_query_repository = InMemoryFriendRelationshipQueryRepository(uow_factory)
    command_service = CommandService(create_builtin_registry())
    send_channel_message = SendChannelMessageUseCase(
        channel_delivery_query=channel_delivery_query,
        command_service=command_service,
        session_store=session_store,
        persistence_publisher=persistence_publisher,
        rate_limiter=InMemoryRateLimiter(time_func=lambda: 0.0),
        config=AppConfig(
            database_url=PostgresDsn("postgresql+asyncpg://test"),
            valkey_url=RedisDsn("redis://test"),
            message_max_length=450,
            rate_limit_messages=10,
            rate_limit_window=10,
        ),
    )
    send_private_message = SendPrivateMessageUseCase(
        target_query=private_message_target_query,
        friend_relationship_query=CheckFriendRelationshipQuery(repository=friend_query_repository),
        command_service=CommandService(create_builtin_registry()),
        session_store=session_store,
        persistence_publisher=persistence_publisher,
        rate_limiter=InMemoryRateLimiter(time_func=lambda: 0.0),
        config=AppConfig(
            database_url=PostgresDsn("postgresql+asyncpg://test"),
            valkey_url=RedisDsn("redis://test"),
            message_max_length=450,
            rate_limit_messages=10,
            rate_limit_window=10,
        ),
    )
    join_channel = JoinChannelUseCase(
        channel_repository=channel_query_repo,
        channel_state=channel_state,
    )
    leave_channel = LeaveChannelUseCase(channel_state=channel_state)

    dispatcher = PacketDispatcher()
    handlers = ChatHandlers(
        send_channel_message=send_channel_message,
        send_private_message=send_private_message,
        join_channel=join_channel,
        leave_channel=leave_channel,
        session_store=session_store,
        packet_queue=packet_queue,
    )
    handlers.register_all(dispatcher)
    friend_handlers = FriendHandlers(
        add_friend=AddFriendUseCase(
            uow_factory=uow_factory,
            system_user_catalog=FriendableSystemUserCatalog.with_bancho_bot(),
        ),
        remove_friend=RemoveFriendUseCase(uow_factory=uow_factory),
        update_friend_only_dm=UpdateFriendOnlyDmUseCase(session_store=session_store),
    )
    friend_handlers.register_all(dispatcher)

    return ChatPipeline(
        dispatcher=dispatcher,
        packet_queue=packet_queue,
        channel_state=channel_state,
        broker=broker,
        sender_id=sender.id,
        target_id=target.id,
        offline_id=offline.id,
    )


class TestChannelMessagePipeline:
    async def test_join_then_channel_message_reaches_other_member_and_fires_event(self) -> None:
        pipeline = await _setup_pipeline()

        await pipeline.dispatcher.dispatch(
            ClientPacketID.JOIN_CHANNEL,
            _channel_payload("#osu"),
            pipeline.sender_id,
        )
        sender_packets = await pipeline.packet_queue.dequeue_all(pipeline.sender_id)
        assert sender_packets == channel_join_success(channel_name="#osu")

        await pipeline.dispatcher.dispatch(
            ClientPacketID.SEND_MESSAGE,
            _message_payload(
                content="hello channel",
                target="#osu",
            ),
            pipeline.sender_id,
        )

        target_packets = await pipeline.packet_queue.dequeue_all(pipeline.target_id)
        assert target_packets == send_message(
            sender="Sender",
            content="hello channel",
            target="#osu",
            sender_id=pipeline.sender_id,
        )
        task = pipeline.broker.find_task("persist_channel_message")
        assert task.calls[-1][0] == (
            pipeline.sender_id,
            "#osu",
            "Sender",
            "hello channel",
        )


class TestPrivateMessagePipeline:
    async def test_online_private_message_reaches_target_and_fires_event(self) -> None:
        pipeline = await _setup_pipeline()

        await pipeline.dispatcher.dispatch(
            ClientPacketID.SEND_PRIVATE_MESSAGE,
            _message_payload(
                content="hello pm",
                target="Target",
            ),
            pipeline.sender_id,
        )

        target_packets = await pipeline.packet_queue.dequeue_all(pipeline.target_id)
        assert target_packets == send_message(
            sender="Sender",
            content="hello pm",
            target="Target",
            sender_id=pipeline.sender_id,
        )
        task = pipeline.broker.find_task("persist_private_message")
        assert task.calls[-1][0] == (
            pipeline.sender_id,
            pipeline.target_id,
            "Sender",
            "Target",
            "hello pm",
        )

    async def test_offline_private_message_does_not_enqueue_but_fires_event(self) -> None:
        pipeline = await _setup_pipeline()

        await pipeline.dispatcher.dispatch(
            ClientPacketID.SEND_PRIVATE_MESSAGE,
            _message_payload(
                content="offline pm",
                target="Offline",
            ),
            pipeline.sender_id,
        )

        offline_packets = await pipeline.packet_queue.dequeue_all(pipeline.offline_id)
        assert offline_packets == b""
        task = pipeline.broker.find_task("persist_private_message")
        assert task.calls[-1][0] == (
            pipeline.sender_id,
            pipeline.offline_id,
            "Sender",
            "Offline",
            "offline pm",
        )

    async def test_friend_only_dms_block_non_friend_and_notify_sender(self) -> None:
        pipeline = await _setup_pipeline()

        await pipeline.dispatcher.dispatch(
            ClientPacketID.CHANGE_FRIENDONLY_DMS,
            b"\x01",
            pipeline.target_id,
        )
        await pipeline.dispatcher.dispatch(
            ClientPacketID.SEND_PRIVATE_MESSAGE,
            _message_payload(
                content="blocked pm",
                target="Target",
            ),
            pipeline.sender_id,
        )

        assert await pipeline.packet_queue.dequeue_all(pipeline.target_id) == b""
        assert await pipeline.packet_queue.dequeue_all(pipeline.sender_id) == user_dm_blocked(
            target="Target"
        )
        task = pipeline.broker.find_task("persist_private_message")
        assert task.calls == []

    async def test_friend_only_dms_allow_sender_friended_by_target(self) -> None:
        pipeline = await _setup_pipeline()

        await pipeline.dispatcher.dispatch(
            ClientPacketID.ADD_FRIEND,
            struct.pack("<i", pipeline.sender_id),
            pipeline.target_id,
        )
        await pipeline.dispatcher.dispatch(
            ClientPacketID.CHANGE_FRIENDONLY_DMS,
            b"\x01",
            pipeline.target_id,
        )
        await pipeline.dispatcher.dispatch(
            ClientPacketID.SEND_PRIVATE_MESSAGE,
            _message_payload(
                content="friend pm",
                target="Target",
            ),
            pipeline.sender_id,
        )

        assert await pipeline.packet_queue.dequeue_all(pipeline.sender_id) == b""
        assert await pipeline.packet_queue.dequeue_all(pipeline.target_id) == send_message(
            sender="Sender",
            content="friend pm",
            target="Target",
            sender_id=pipeline.sender_id,
        )
        task = pipeline.broker.find_task("persist_private_message")
        assert task.calls[-1][0] == (
            pipeline.sender_id,
            pipeline.target_id,
            "Sender",
            "Target",
            "friend pm",
        )

    async def test_banchobot_pm_response_bypasses_sender_friend_only_dms(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pipeline = await _setup_pipeline()

        def fixed_randint(minimum: int, maximum: int) -> int:
            assert minimum == 0
            assert maximum == 100
            return 50

        monkeypatch.setattr(random, "randint", fixed_randint)

        await pipeline.dispatcher.dispatch(
            ClientPacketID.CHANGE_FRIENDONLY_DMS,
            b"\x01",
            pipeline.sender_id,
        )
        await pipeline.dispatcher.dispatch(
            ClientPacketID.SEND_PRIVATE_MESSAGE,
            _message_payload(
                content="!roll 100",
                target=BANCHO_BOT_IDENTITY.username,
            ),
            pipeline.sender_id,
        )

        assert await pipeline.packet_queue.dequeue_all(pipeline.sender_id) == send_message(
            sender=BANCHO_BOT_IDENTITY.username,
            content="Sender rolls 50 point(s)",
            target="Sender",
            sender_id=BANCHO_BOT_IDENTITY.user_id,
        )


class TestCommandPipeline:
    async def test_roll_command_delivers_message_and_banchobot_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pipeline = await _setup_pipeline()

        def fixed_randint(minimum: int, maximum: int) -> int:
            assert minimum == 0
            assert maximum == 100
            return 50

        monkeypatch.setattr(random, "randint", fixed_randint)

        await pipeline.dispatcher.dispatch(
            ClientPacketID.JOIN_CHANNEL,
            _channel_payload("#osu"),
            pipeline.sender_id,
        )
        _ = await pipeline.packet_queue.dequeue_all(pipeline.sender_id)

        await pipeline.dispatcher.dispatch(
            ClientPacketID.SEND_MESSAGE,
            _message_payload(
                content="!roll 100",
                target="#osu",
            ),
            pipeline.sender_id,
        )

        bot_response = send_message(
            sender=BANCHO_BOT_IDENTITY.username,
            content="Sender rolls 50 point(s)",
            target="#osu",
            sender_id=BANCHO_BOT_IDENTITY.user_id,
        )
        target_packets = await pipeline.packet_queue.dequeue_all(pipeline.target_id)
        assert (
            target_packets
            == send_message(
                sender="Sender",
                content="!roll 100",
                target="#osu",
                sender_id=pipeline.sender_id,
            )
            + bot_response
        )
        sender_packets = await pipeline.packet_queue.dequeue_all(pipeline.sender_id)
        assert sender_packets == bot_response


class TestDisconnectCleanupPipeline:
    async def test_user_disconnected_removes_user_from_all_channels(self) -> None:
        pipeline = await _setup_pipeline()
        await pipeline.channel_state.add_member("#announce", pipeline.sender_id)
        await pipeline.channel_state.add_member("#osu", pipeline.sender_id)

        event_bus = InMemoryLocalEventBus()
        chat_listeners = ChatListeners(
            channel_state=pipeline.channel_state,
        )
        chat_listeners.register_all(event_bus)

        await event_bus.fire(UserDisconnected(user_id=pipeline.sender_id))

        assert await pipeline.channel_state.get_user_channels(pipeline.sender_id) == set()

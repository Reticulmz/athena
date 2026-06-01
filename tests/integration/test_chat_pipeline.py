from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from caterpillar.model import pack
from pydantic import PostgresDsn, RedisDsn

from osu_server.config import AppConfig
from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent
from osu_server.domain.role import Privileges
from osu_server.domain.session import SessionData
from osu_server.domain.users.events import UserDisconnected
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.chat_repository import InMemoryChatRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.channel_service import ChannelService
from osu_server.services.chat_service import ChatService
from osu_server.services.command_service import CommandService
from osu_server.services.private_message_service import PrivateMessageService
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.handlers.chat import ChatHandlers
from osu_server.transports.bancho.listeners.chat import ChatListeners
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.s2c.chat import channel_join_success, send_message
from osu_server.transports.bancho.protocol.types import BanchoString, Message
from tests.factories.domain import make_channel, make_user

if TYPE_CHECKING:
    import pytest


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
    captured_events: list[object]
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


def _message_payload(*, sender: str, content: str, target: str, sender_id: int) -> bytes:
    return pack(Message(sender=sender, content=content, target=target, sender_id=sender_id))


def _channel_payload(channel_name: str) -> bytes:
    return pack(channel_name, BanchoString)


async def _setup_pipeline() -> ChatPipeline:
    user_repo = InMemoryUserRepository()
    session_store = InMemorySessionStore()
    channel_repo = InMemoryChannelRepository()
    channel_state = InMemoryChannelStateStore()
    packet_queue = InMemoryPacketQueue()
    event_bus = InMemoryEventBus()
    broker = SpyBroker()
    captured_events: list[object] = []

    bot = await user_repo.create(make_user(username="BanchoBot", email="bot@example.com"))
    sender = await user_repo.create(make_user(username="Sender", email="sender@example.com"))
    target = await user_repo.create(make_user(username="Target", email="target@example.com"))
    offline = await user_repo.create(make_user(username="Offline", email="offline@example.com"))
    assert bot.id == CommandService.BANCHO_BOT_ID

    await session_store.create(sender.id, "sender-token", _session(sender.id, sender.username))
    await session_store.create(target.id, "target-token", _session(target.id, target.username))

    for user_id in (sender.id, target.id, offline.id):
        await packet_queue.refresh_ttl(user_id, ttl=300)

    _ = await channel_repo.create(make_channel(name="#osu", auto_join=False))
    await channel_state.add_member("#osu", target.id)

    async def capture_event(event: object) -> None:
        captured_events.append(event)

    event_bus.subscribe(ChannelMessageSent, capture_event)
    event_bus.subscribe(PrivateMessageSent, capture_event)
    chat_listeners = ChatListeners(
        broker=broker,  # pyright: ignore[reportArgumentType]
        channel_state=channel_state,
    )
    chat_listeners.register_all(event_bus)

    channel_service = ChannelService(
        channel_repo=channel_repo,
        channel_state=channel_state,
    )
    chat_service = ChatService(
        channel_service=channel_service,
        private_message_service=PrivateMessageService(
            user_repo=user_repo,
            session_store=session_store,
        ),
        command_service=CommandService(),
        session_store=session_store,
        event_bus=event_bus,
        rate_limiter=InMemoryRateLimiter(time_func=lambda: 0.0),
        config=AppConfig(
            database_url=PostgresDsn("postgresql+asyncpg://test"),
            valkey_url=RedisDsn("redis://test"),
            message_max_length=450,
            rate_limit_messages=10,
            rate_limit_window=10,
        ),
        chat_repository=InMemoryChatRepository(),
    )

    dispatcher = PacketDispatcher()
    handlers = ChatHandlers(
        chat_service=chat_service,
        channel_service=channel_service,
        session_store=session_store,
        packet_queue=packet_queue,
    )
    handlers.register_all(dispatcher)

    return ChatPipeline(
        dispatcher=dispatcher,
        packet_queue=packet_queue,
        channel_state=channel_state,
        broker=broker,
        captured_events=captured_events,
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
                sender="Sender",
                content="hello channel",
                target="#osu",
                sender_id=pipeline.sender_id,
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
        assert isinstance(pipeline.captured_events[-1], ChannelMessageSent)
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
                sender="Sender",
                content="hello pm",
                target="Target",
                sender_id=pipeline.sender_id,
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
        assert isinstance(pipeline.captured_events[-1], PrivateMessageSent)
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
                sender="Sender",
                content="offline pm",
                target="Offline",
                sender_id=pipeline.sender_id,
            ),
            pipeline.sender_id,
        )

        offline_packets = await pipeline.packet_queue.dequeue_all(pipeline.offline_id)
        assert offline_packets == b""
        assert isinstance(pipeline.captured_events[-1], PrivateMessageSent)
        task = pipeline.broker.find_task("persist_private_message")
        assert task.calls[-1][0] == (
            pipeline.sender_id,
            pipeline.offline_id,
            "Sender",
            "Offline",
            "offline pm",
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
                sender="Sender",
                content="!roll 100",
                target="#osu",
                sender_id=pipeline.sender_id,
            ),
            pipeline.sender_id,
        )

        bot_response = send_message(
            sender=CommandService.BANCHO_BOT_NAME,
            content="Sender rolls 50 point(s)",
            target="#osu",
            sender_id=CommandService.BANCHO_BOT_ID,
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

        event_bus = InMemoryEventBus()
        chat_listeners = ChatListeners(
            broker=pipeline.broker,  # pyright: ignore[reportArgumentType]
            channel_state=pipeline.channel_state,
        )
        chat_listeners.register_all(event_bus)

        await event_bus.fire(UserDisconnected(user_id=pipeline.sender_id))

        assert await pipeline.channel_state.get_user_channels(pipeline.sender_id) == set()

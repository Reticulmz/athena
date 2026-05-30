import random
import time
from datetime import UTC, datetime

import pytest
from pydantic import PostgresDsn, RedisDsn

from osu_server.config import AppConfig
from osu_server.domain.channel import Channel, ChannelType
from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent
from osu_server.domain.session import SessionData
from osu_server.domain.user import User
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.memory.channel_state_store import (
    InMemoryChannelStateStore,
)
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.channel_service import ChannelService
from osu_server.services.chat_service import ChatService
from osu_server.services.command_service import CommandService
from osu_server.services.private_message_service import PrivateMessageService

_NOW = datetime.now(UTC)
_BYPASS_ACL = 1 << 9  # Privileges.BYPASS_CHANNEL_ACL


@pytest.fixture
def channel_repo() -> InMemoryChannelRepository:
    return InMemoryChannelRepository()


@pytest.fixture
def channel_state() -> InMemoryChannelStateStore:
    return InMemoryChannelStateStore()


@pytest.fixture
def user_repo() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
async def session_store() -> InMemorySessionStore:
    store = InMemorySessionStore()
    await store.create(
        user_id=1,
        token="sender_session",
        data=SessionData(
            user_id=1,
            username="sender",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=0,
        ),
    )
    return store


@pytest.fixture
def captured_events() -> list[object]:
    return []


@pytest.fixture
def event_bus(captured_events: list[object]) -> InMemoryEventBus:
    bus = InMemoryEventBus()

    async def capture(event: object) -> None:
        captured_events.append(event)

    bus.subscribe(ChannelMessageSent, capture)
    bus.subscribe(PrivateMessageSent, capture)
    return bus


@pytest.fixture
def rate_limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter(time_func=lambda: 0.0)


@pytest.fixture
def config() -> AppConfig:
    return AppConfig(
        database_url=PostgresDsn("postgresql+asyncpg://test"),
        valkey_url=RedisDsn("redis://test"),
        message_max_length=50,
        rate_limit_messages=10,
        rate_limit_window=10,
    )


@pytest.fixture
async def channel_service(
    channel_repo: InMemoryChannelRepository,
    channel_state: InMemoryChannelStateStore,
) -> ChannelService:
    channel = Channel(
        id=0,  # auto-assigned by repository
        name="#osu",
        topic="",
        channel_type=ChannelType.PUBLIC,
        auto_join=False,
        rate_limit_messages=None,
        rate_limit_window=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    _ = await channel_repo.create(channel)

    # Sender (1) + delivery targets (2, 3) as channel members
    await channel_state.add_member("#osu", 1)
    await channel_state.add_member("#osu", 2)
    await channel_state.add_member("#osu", 3)

    return ChannelService(channel_repo=channel_repo, channel_state=channel_state)


@pytest.fixture
def private_message_service(
    user_repo: InMemoryUserRepository,
    session_store: InMemorySessionStore,
) -> PrivateMessageService:
    return PrivateMessageService(user_repo=user_repo, session_store=session_store)


@pytest.fixture
def command_service() -> CommandService:
    return CommandService()


@pytest.fixture
def chat_service(
    channel_service: ChannelService,
    private_message_service: PrivateMessageService,
    command_service: CommandService,
    session_store: InMemorySessionStore,
    event_bus: InMemoryEventBus,
    rate_limiter: InMemoryRateLimiter,
    config: AppConfig,
) -> ChatService:
    return ChatService(
        channel_service=channel_service,
        private_message_service=private_message_service,
        command_service=command_service,
        session_store=session_store,
        event_bus=event_bus,
        rate_limiter=rate_limiter,
        config=config,
    )


@pytest.mark.asyncio
async def test_send_channel_message_success(
    chat_service: ChatService,
    captured_events: list[object],
) -> None:
    res = await chat_service.send_channel_message(
        sender_id=1,
        sender_name="sender",
        channel_name="#osu",
        content="hello",
        user_privileges=_BYPASS_ACL,
        user_role_ids=[],
    )

    assert res is not None
    assert res.delivered_to == {2, 3}
    assert res.content == "hello"
    assert res.command_response is None

    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, ChannelMessageSent)
    assert event.content == "hello"
    assert event.sender_id == 1
    assert event.channel_name == "#osu"


@pytest.mark.asyncio
async def test_send_private_message_success(
    chat_service: ChatService,
    user_repo: InMemoryUserRepository,
    session_store: InMemorySessionStore,
    captured_events: list[object],
) -> None:
    # Seed sender user (consumes id=1) then target user (id=2)
    sender = User(
        id=0,
        username="sender",
        safe_username="sender",
        email="sender@test.local",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )
    _ = await user_repo.create(sender)

    target = User(
        id=0,
        username="target",
        safe_username="target",
        email="target@test.local",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )
    created_target = await user_repo.create(target)

    # Create session for target so is_online=True
    await session_store.create(
        user_id=created_target.id,
        token="target_session",
        data=SessionData(
            user_id=created_target.id,
            username="target",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=0,
        ),
    )

    res = await chat_service.send_private_message(
        sender_id=1,
        sender_name="sender",
        target_name="target",
        content="hello PM",
    )

    assert res is not None
    assert res.target_id == created_target.id
    assert res.is_online is True
    assert res.content == "hello PM"
    assert res.command_response is None

    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, PrivateMessageSent)
    assert event.content == "hello PM"
    assert event.sender_id == 1
    assert event.target_id == created_target.id


@pytest.mark.asyncio
async def test_silenced_user_rejected(
    chat_service: ChatService,
    session_store: InMemorySessionStore,
    captured_events: list[object],
) -> None:
    # Overwrite sender session with silenced status
    await session_store.create(
        user_id=1,
        token="silenced_session",
        data=SessionData(
            user_id=1,
            username="sender",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=int(time.time()) + 3600,
        ),
    )

    res = await chat_service.send_channel_message(
        sender_id=1,
        sender_name="sender",
        channel_name="#osu",
        content="hello",
        user_privileges=_BYPASS_ACL,
    )
    assert res is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_rate_limited_rejected(
    chat_service: ChatService,
    rate_limiter: InMemoryRateLimiter,
    config: AppConfig,
    captured_events: list[object],
) -> None:
    # Pre-fill rate limiter to exhaust the limit
    limit = config.rate_limit_messages  # 10
    window = config.rate_limit_window  # 10
    for _ in range(limit):
        _ = await rate_limiter.check(user_id=1, limit=limit, window=window)

    res = await chat_service.send_channel_message(
        sender_id=1,
        sender_name="sender",
        channel_name="#osu",
        content="hello",
        user_privileges=_BYPASS_ACL,
    )
    assert res is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_empty_message_rejected(
    chat_service: ChatService,
    captured_events: list[object],
) -> None:
    res = await chat_service.send_channel_message(
        sender_id=1,
        sender_name="sender",
        channel_name="#osu",
        content="",
        user_privileges=_BYPASS_ACL,
    )
    assert res is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_long_message_rejected(
    chat_service: ChatService,
    captured_events: list[object],
) -> None:
    long_msg = "a" * 100
    res = await chat_service.send_channel_message(
        sender_id=1,
        sender_name="sender",
        channel_name="#osu",
        content=long_msg,
        user_privileges=_BYPASS_ACL,
    )

    assert res is None
    assert len(captured_events) == 0


@pytest.mark.asyncio
async def test_command_execution(
    chat_service: ChatService,
    captured_events: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mock_randint(_a: int, _b: int) -> int:
        return 50

    monkeypatch.setattr(random, "randint", mock_randint)

    res = await chat_service.send_channel_message(
        sender_id=1,
        sender_name="sender",
        channel_name="#osu",
        content="!roll 100",
        user_privileges=_BYPASS_ACL,
    )

    assert res is not None
    assert res.delivered_to == {2, 3}
    assert res.command_response is not None
    assert res.command_response.target == "#osu"
    assert res.command_response.content == "sender rolls 50 point(s)"

    # Command messages are also delivered to channel members (Req 8.2)
    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, ChannelMessageSent)
    assert event.content == "!roll 100"
    assert event.sender_id == 1
    assert event.channel_name == "#osu"

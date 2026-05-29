import time
from unittest.mock import AsyncMock

import pytest
from pydantic import PostgresDsn, RedisDsn

from osu_server.config import AppConfig
from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent
from osu_server.domain.session import SessionData
from osu_server.services.chat_service import ChatService


@pytest.fixture
def channel_service() -> AsyncMock:
    srv = AsyncMock()
    srv.get_channel = AsyncMock(return_value=None)
    srv.get_delivery_targets = AsyncMock(return_value={2, 3})
    return srv


@pytest.fixture
def private_message_service() -> AsyncMock:
    srv = AsyncMock()
    srv.resolve_target = AsyncMock(return_value=(True, 2, True))
    return srv


@pytest.fixture
def command_service() -> AsyncMock:
    srv = AsyncMock()
    srv.execute = AsyncMock(return_value=None)
    return srv


@pytest.fixture
def session_store() -> AsyncMock:
    store = AsyncMock()
    store.get_by_user = AsyncMock(
        return_value=SessionData(
            user_id=1,
            username="test",
            privileges=0,
            country="JP",
            osu_version="test",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            silence_end=0,
        )
    )
    return store


@pytest.fixture
def event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.fire = AsyncMock()
    return bus


@pytest.fixture
def rate_limiter() -> AsyncMock:
    limiter = AsyncMock()
    limiter.check = AsyncMock(return_value=True)
    return limiter


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
def chat_service(
    channel_service: AsyncMock,
    private_message_service: AsyncMock,
    command_service: AsyncMock,
    session_store: AsyncMock,
    event_bus: AsyncMock,
    rate_limiter: AsyncMock,
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
    chat_service: ChatService, event_bus: AsyncMock
) -> None:
    res = await chat_service.send_channel_message(
        sender_id=1,
        sender_name="sender",
        channel_name="#osu",
        content="hello",
        user_privileges=0,
        user_role_ids=[],
    )

    assert res is not None
    assert res.delivered_to == {2, 3}
    assert res.content == "hello"
    assert res.command_response is None

    event_bus.fire.assert_called_once()  # pyright: ignore[reportAny]
    event = event_bus.fire.call_args[0][0]  # pyright: ignore[reportAny]
    assert isinstance(event, ChannelMessageSent)
    assert event.content == "hello"
    assert event.sender_id == 1
    assert event.channel_name == "#osu"


@pytest.mark.asyncio
async def test_send_private_message_success(
    chat_service: ChatService, event_bus: AsyncMock
) -> None:
    res = await chat_service.send_private_message(
        sender_id=1,
        sender_name="sender",
        target_name="target",
        content="hello PM",
    )

    assert res is not None
    assert res.target_id == 2
    assert res.is_online is True
    assert res.content == "hello PM"
    assert res.command_response is None

    event_bus.fire.assert_called_once()  # pyright: ignore[reportAny]
    event = event_bus.fire.call_args[0][0]  # pyright: ignore[reportAny]
    assert isinstance(event, PrivateMessageSent)
    assert event.content == "hello PM"
    assert event.sender_id == 1
    assert event.target_id == 2


@pytest.mark.asyncio
async def test_silenced_user_rejected(
    chat_service: ChatService, session_store: AsyncMock, event_bus: AsyncMock
) -> None:
    session_store.get_by_user.return_value.silence_end = (  # pyright: ignore[reportAny]
        int(time.time()) + 3600
    )

    res = await chat_service.send_channel_message(1, "sender", "#osu", "hello")
    assert res is None
    event_bus.fire.assert_not_called()  # pyright: ignore[reportAny]


@pytest.mark.asyncio
async def test_rate_limited_rejected(
    chat_service: ChatService, rate_limiter: AsyncMock, event_bus: AsyncMock
) -> None:
    rate_limiter.check.return_value = False  # pyright: ignore[reportAny]

    res = await chat_service.send_channel_message(1, "sender", "#osu", "hello")
    assert res is None
    event_bus.fire.assert_not_called()  # pyright: ignore[reportAny]


@pytest.mark.asyncio
async def test_empty_message_rejected(chat_service: ChatService, event_bus: AsyncMock) -> None:
    res = await chat_service.send_channel_message(1, "sender", "#osu", "")
    assert res is None
    event_bus.fire.assert_not_called()  # pyright: ignore[reportAny]


@pytest.mark.asyncio
async def test_long_message_truncated(chat_service: ChatService, event_bus: AsyncMock) -> None:
    long_msg = "a" * 100
    res = await chat_service.send_channel_message(1, "sender", "#osu", long_msg)

    assert res is not None
    assert res.content == "a" * 50

    event = event_bus.fire.call_args[0][0]  # pyright: ignore[reportAny]
    assert isinstance(event, ChannelMessageSent)
    assert event.content == "a" * 50


@pytest.mark.asyncio
async def test_command_execution(
    chat_service: ChatService, command_service: AsyncMock, event_bus: AsyncMock
) -> None:
    command_service.execute.return_value = ("#osu", "BanchoBot response")  # pyright: ignore[reportAny]

    res = await chat_service.send_channel_message(1, "sender", "#osu", "!roll")

    assert res is not None
    assert res.delivered_to is None
    assert res.command_response is not None
    assert res.command_response.target == "#osu"
    assert res.command_response.content == "BanchoBot response"

    event_bus.fire.assert_not_called()  # pyright: ignore[reportAny]

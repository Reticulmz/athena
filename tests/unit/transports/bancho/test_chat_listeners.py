"""Tests for ChatListeners — message persistence enqueue + disconnect cleanup."""

from __future__ import annotations

import pytest
import structlog.testing

from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent
from osu_server.domain.users.events import UserDisconnected
from osu_server.transports.bancho.listeners.chat import ChatListeners

# ── Stubs ────────────────────────────────────────────────────────────────


class StubTask:
    """taskiq タスクスタブ。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def kiq(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


class StubBroker:
    """AsyncBroker スタブ — find_task でスタブタスクを返す。"""

    def __init__(self, *, missing_tasks: set[str] | None = None) -> None:
        self._tasks: dict[str, StubTask] = {}
        self._missing_tasks: set[str] = missing_tasks or set()

    def find_task(self, name: str) -> StubTask | None:
        if name in self._missing_tasks:
            return None
        if name not in self._tasks:
            self._tasks[name] = StubTask()
        return self._tasks[name]


class StubChannelStateStore:
    """ChannelStateStore スタブ。"""

    removed_from: set[str]
    removed_user_ids: list[int]

    def __init__(self, removed_from: set[str] | None = None) -> None:
        self.removed_from = removed_from or {"#osu", "#test"}
        self.removed_user_ids = []

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        self.removed_user_ids.append(user_id)
        return self.removed_from


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def broker() -> StubBroker:
    return StubBroker()


@pytest.fixture
def channel_state() -> StubChannelStateStore:
    return StubChannelStateStore()


@pytest.fixture
def listeners(
    broker: StubBroker,
    channel_state: StubChannelStateStore,
) -> ChatListeners:
    return ChatListeners(
        broker=broker,  # pyright: ignore[reportArgumentType]
        channel_state=channel_state,  # pyright: ignore[reportArgumentType]
    )


# ── on_channel_message_sent ─────────────────────────────────────────────


class TestOnChannelMessageSent:
    async def test_enqueues_persist_channel_message_job(
        self,
        listeners: ChatListeners,
        broker: StubBroker,
    ) -> None:
        event = ChannelMessageSent(
            sender_id=1,
            sender_name="test_user",
            channel_name="#osu",
            content="hello",
        )

        await listeners.on_channel_message_sent(event)

        task = broker.find_task("persist_channel_message")
        assert task is not None
        assert len(task.calls) == 1
        args, kwargs = task.calls[0]
        assert args == (1, "#osu", "test_user", "hello")
        assert kwargs == {}

    async def test_logs_missing_persist_channel_message_task(
        self,
        channel_state: StubChannelStateStore,
    ) -> None:
        broker = StubBroker(missing_tasks={"persist_channel_message"})
        listeners = ChatListeners(
            broker=broker,  # pyright: ignore[reportArgumentType]
            channel_state=channel_state,  # pyright: ignore[reportArgumentType]
        )
        event = ChannelMessageSent(
            sender_id=1,
            sender_name="test_user",
            channel_name="#osu",
            content="hello",
        )

        with structlog.testing.capture_logs() as logs:
            await listeners.on_channel_message_sent(event)

        entries = [
            entry for entry in logs if entry.get("event") == "chat_persistence_task_not_registered"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "persist_channel_message"
        assert entries[0]["sender_id"] == 1
        assert entries[0]["channel_name"] == "#osu"
        assert entries[0]["log_level"] == "error"


# ── on_private_message_sent ─────────────────────────────────────────────


class TestOnPrivateMessageSent:
    async def test_enqueues_persist_private_message_job(
        self,
        listeners: ChatListeners,
        broker: StubBroker,
    ) -> None:
        event = PrivateMessageSent(
            sender_id=1,
            sender_name="test_user",
            target_id=2,
            target_name="other_user",
            content="secret",
        )

        await listeners.on_private_message_sent(event)

        task = broker.find_task("persist_private_message")
        assert task is not None
        assert len(task.calls) == 1
        args, kwargs = task.calls[0]
        assert args == (1, 2, "test_user", "other_user", "secret")
        assert kwargs == {}

    async def test_logs_missing_persist_private_message_task(
        self,
        channel_state: StubChannelStateStore,
    ) -> None:
        broker = StubBroker(missing_tasks={"persist_private_message"})
        listeners = ChatListeners(
            broker=broker,  # pyright: ignore[reportArgumentType]
            channel_state=channel_state,  # pyright: ignore[reportArgumentType]
        )
        event = PrivateMessageSent(
            sender_id=1,
            sender_name="test_user",
            target_id=2,
            target_name="other_user",
            content="secret",
        )

        with structlog.testing.capture_logs() as logs:
            await listeners.on_private_message_sent(event)

        entries = [
            entry for entry in logs if entry.get("event") == "chat_persistence_task_not_registered"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "persist_private_message"
        assert entries[0]["sender_id"] == 1
        assert entries[0]["target_id"] == 2
        assert entries[0]["log_level"] == "error"


# ── on_user_disconnected ────────────────────────────────────────────────


class TestOnUserDisconnected:
    async def test_removes_user_from_all_channels(
        self,
        listeners: ChatListeners,
        channel_state: StubChannelStateStore,
    ) -> None:
        event = UserDisconnected(user_id=42)

        await listeners.on_user_disconnected(event)

        assert channel_state.removed_user_ids == [42]

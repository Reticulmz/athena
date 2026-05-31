"""Tests for taskiq chat persistence job adapters."""

from __future__ import annotations

import inspect
import subprocess
import sys

import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage

from osu_server.jobs import chat_persistence, register_all_jobs
from osu_server.jobs.chat_persistence import (
    persist_channel_message,
    persist_private_message,
)
from osu_server.repositories.interfaces.chat_repository import ChatPersistenceResult


class StubChatService:
    """ChatService test double that records persistence calls."""

    channel_calls: list[tuple[int, str, str]]
    private_calls: list[tuple[int, int, str]]

    def __init__(self) -> None:
        self.channel_calls = []
        self.private_calls = []

    async def persist_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        self.channel_calls.append((sender_id, channel_name, content))
        return ChatPersistenceResult.success_result()

    async def persist_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        self.private_calls.append((sender_id, target_id, content))
        return ChatPersistenceResult.success_result()


def make_context(chat_service: object | None = None) -> Context:
    """Create a taskiq Context carrying optional ChatService runtime state."""
    broker = InMemoryBroker()
    if chat_service is not None:
        broker.state.chat_service = chat_service
    message = TaskiqMessage(
        task_id="test-id",
        task_name="test-task",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


class TestPersistChannelMessage:
    async def test_delegates_to_chat_service_persistence_use_case(self) -> None:
        chat_service = StubChatService()
        context = make_context(chat_service)

        await persist_channel_message(
            sender_id=1,
            channel_name="#osu",
            sender_name="sender",
            content="hello",
            context=context,
        )

        assert chat_service.channel_calls == [(1, "#osu", "hello")]
        assert chat_service.private_calls == []

    async def test_logs_missing_runtime_state(self) -> None:
        context = make_context()

        with structlog.testing.capture_logs() as logs:
            await persist_channel_message(
                sender_id=1,
                channel_name="#osu",
                sender_name="sender",
                content="hello",
                context=context,
            )

        entries = [
            entry for entry in logs if entry.get("event") == "chat_persistence_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "persist_channel_message"
        assert entries[0]["sender_id"] == 1
        assert entries[0]["channel_name"] == "#osu"
        assert entries[0]["log_level"] == "error"


class TestPersistPrivateMessage:
    async def test_delegates_to_chat_service_persistence_use_case(self) -> None:
        chat_service = StubChatService()
        context = make_context(chat_service)

        await persist_private_message(
            sender_id=1,
            target_id=2,
            sender_name="sender",
            target_name="target",
            content="secret",
            context=context,
        )

        assert chat_service.private_calls == [(1, 2, "secret")]
        assert chat_service.channel_calls == []

    async def test_logs_missing_runtime_state(self) -> None:
        context = make_context()

        with structlog.testing.capture_logs() as logs:
            await persist_private_message(
                sender_id=1,
                target_id=2,
                sender_name="sender",
                target_name="target",
                content="secret",
                context=context,
            )

        entries = [
            entry for entry in logs if entry.get("event") == "chat_persistence_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "persist_private_message"
        assert entries[0]["sender_id"] == 1
        assert entries[0]["target_id"] == 2
        assert entries[0]["log_level"] == "error"


def test_register_all_jobs_attaches_loaded_chat_persistence_tasks_to_broker() -> None:
    broker = InMemoryBroker()

    register_all_jobs(broker)

    assert broker.find_task("persist_channel_message") is not None
    assert broker.find_task("persist_private_message") is not None


def test_register_all_jobs_loads_chat_persistence_tasks_in_fresh_process() -> None:
    code = """
from taskiq import InMemoryBroker
from osu_server.jobs import register_all_jobs

broker = InMemoryBroker()
register_all_jobs(broker)
assert broker.find_task("persist_channel_message") is not None
assert broker.find_task("persist_private_message") is not None
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_chat_persistence_job_stays_queue_adapter_only() -> None:
    source = inspect.getsource(chat_persistence)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories.sqlalchemy" not in source
    assert "ChannelService" not in source
    assert "CommandService" not in source

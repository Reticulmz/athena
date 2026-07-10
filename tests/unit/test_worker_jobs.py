"""Tests for taskiq chat persistence job adapters."""

from __future__ import annotations

import inspect
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage

from osu_server.domain.chat import ChatPersistenceResult
from osu_server.jobs import chat_persistence, register_all_jobs
from osu_server.jobs.chat_persistence import (
    persist_channel_message,
    persist_private_message,
)

if TYPE_CHECKING:
    from osu_server.services.commands.chat import (
        PersistChannelMessageCommand,
        PersistPrivateMessageCommand,
    )


class StubChannelMessagePersistenceUseCase:
    """Use-case test double that records channel persistence calls."""

    channel_calls: list[tuple[int, str, str]]

    def __init__(self) -> None:
        self.channel_calls = []

    async def execute(self, command: PersistChannelMessageCommand) -> ChatPersistenceResult:
        self.channel_calls.append((command.sender_id, command.channel_name, command.content))
        return ChatPersistenceResult.success_result()


class StubPrivateMessagePersistenceUseCase:
    """Use-case test double that records private persistence calls."""

    private_calls: list[tuple[int, int, str]]

    def __init__(self) -> None:
        self.private_calls = []

    async def execute(self, command: PersistPrivateMessageCommand) -> ChatPersistenceResult:
        self.private_calls.append((command.sender_id, command.target_id, command.content))
        return ChatPersistenceResult.success_result()


def make_context(
    *,
    channel_use_case: object | None = None,
    private_use_case: object | None = None,
) -> Context:
    """Create a taskiq Context carrying optional chat persistence use-cases."""
    broker = InMemoryBroker()
    if channel_use_case is not None:
        broker.state.persist_channel_message_use_case = channel_use_case
    if private_use_case is not None:
        broker.state.persist_private_message_use_case = private_use_case
    message = TaskiqMessage(
        task_id="test-id",
        task_name="test-task",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


class TestPersistChannelMessage:
    async def test_delegates_to_channel_persistence_use_case(self) -> None:
        use_case = StubChannelMessagePersistenceUseCase()
        context = make_context(channel_use_case=use_case)

        await persist_channel_message(
            sender_id=1,
            channel_name="#osu",
            sender_name="sender",
            content="hello",
            context=context,
        )

        assert use_case.channel_calls == [(1, "#osu", "hello")]

    async def test_logs_missing_runtime_state(self) -> None:
        context = make_context()

        with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError):
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
    async def test_delegates_to_private_persistence_use_case(self) -> None:
        use_case = StubPrivateMessagePersistenceUseCase()
        context = make_context(private_use_case=use_case)

        await persist_private_message(
            sender_id=1,
            target_id=2,
            sender_name="sender",
            target_name="target",
            content="secret",
            context=context,
        )

        assert use_case.private_calls == [(1, 2, "secret")]

    async def test_logs_missing_runtime_state(self) -> None:
        context = make_context()

        with structlog.testing.capture_logs() as logs, pytest.raises(RuntimeError):
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
    assert broker.find_task("fetch_beatmap_metadata") is not None
    assert broker.find_task("fetch_beatmap_file") is not None
    assert broker.find_task("calculate_score_performance") is not None
    assert broker.find_task("process_performance_recalculation_batch") is not None
    assert broker.find_task("account_replay_download") is not None


def test_register_all_jobs_loads_chat_persistence_tasks_in_fresh_process() -> None:
    code = """
from taskiq import InMemoryBroker
from osu_server.jobs import register_all_jobs

broker = InMemoryBroker()
register_all_jobs(broker)
assert broker.find_task("persist_channel_message") is not None
assert broker.find_task("persist_private_message") is not None
assert broker.find_task("fetch_beatmap_metadata") is not None
assert broker.find_task("fetch_beatmap_file") is not None
assert broker.find_task("calculate_score_performance") is not None
assert broker.find_task("process_performance_recalculation_batch") is not None
assert broker.find_task("account_replay_download") is not None
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

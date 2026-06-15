"""Tests for taskiq chat persistence work publisher."""

from __future__ import annotations

import structlog.testing

from osu_server.jobs.chat_persistence_publisher import TaskiqChatPersistenceWorkPublisher
from osu_server.services.commands.chat import (
    ChannelMessagePersistenceWork,
    PrivateMessagePersistenceWork,
)


class StubTask:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail: bool = fail
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def kiq(self, *args: object, **kwargs: object) -> None:
        if self.fail:
            msg = "enqueue failed"
            raise RuntimeError(msg)
        self.calls.append((args, kwargs))


class StubBroker:
    def __init__(self, *, missing_tasks: set[str] | None = None) -> None:
        self.tasks: dict[str, StubTask] = {}
        self.missing_tasks: set[str] = missing_tasks or set()

    def find_task(self, task_name: str) -> StubTask | None:
        if task_name in self.missing_tasks:
            return None
        task = self.tasks.get(task_name)
        if task is None:
            task = StubTask()
            self.tasks[task_name] = task
        return task


async def test_publish_channel_message_enqueues_existing_task_payload() -> None:
    broker = StubBroker()
    publisher = TaskiqChatPersistenceWorkPublisher(broker)

    await publisher.publish_channel_message(
        ChannelMessagePersistenceWork(
            sender_id=1,
            sender_name="sender",
            channel_name="#osu",
            content="hello",
        )
    )

    task = broker.find_task("persist_channel_message")
    assert task is not None
    assert task.calls == [((1, "#osu", "sender", "hello"), {})]


async def test_publish_private_message_enqueues_existing_task_payload() -> None:
    broker = StubBroker()
    publisher = TaskiqChatPersistenceWorkPublisher(broker)

    await publisher.publish_private_message(
        PrivateMessagePersistenceWork(
            sender_id=1,
            sender_name="sender",
            target_id=2,
            target_name="target",
            content="hello",
        )
    )

    task = broker.find_task("persist_private_message")
    assert task is not None
    assert task.calls == [((1, 2, "sender", "target", "hello"), {})]


async def test_missing_task_is_logged_and_not_raised() -> None:
    broker = StubBroker(missing_tasks={"persist_channel_message"})
    publisher = TaskiqChatPersistenceWorkPublisher(broker)

    with structlog.testing.capture_logs() as logs:
        await publisher.publish_channel_message(
            ChannelMessagePersistenceWork(
                sender_id=1,
                sender_name="sender",
                channel_name="#osu",
                content="hello",
            )
        )

    entries = [
        entry for entry in logs if entry.get("event") == "chat_persistence_task_not_registered"
    ]
    assert len(entries) == 1
    assert entries[0]["task_name"] == "persist_channel_message"
    assert entries[0]["sender_id"] == 1


async def test_enqueue_failure_is_logged_and_not_raised() -> None:
    broker = StubBroker()
    broker.tasks["persist_private_message"] = StubTask(fail=True)
    publisher = TaskiqChatPersistenceWorkPublisher(broker)

    with structlog.testing.capture_logs() as logs:
        await publisher.publish_private_message(
            PrivateMessagePersistenceWork(
                sender_id=1,
                sender_name="sender",
                target_id=2,
                target_name="target",
                content="hello",
            )
        )

    entries = [entry for entry in logs if entry.get("event") == "chat_persistence_enqueue_failed"]
    assert len(entries) == 1
    assert entries[0]["task_name"] == "persist_private_message"
    assert entries[0]["sender_id"] == 1

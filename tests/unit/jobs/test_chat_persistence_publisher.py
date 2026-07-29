"""Chat永続化workをTaskiqへ発行するpublisherのunit testを提供する."""

from __future__ import annotations

import structlog.testing

from osu_server.jobs.chat_persistence_publisher import TaskiqChatPersistenceWorkPublisher
from osu_server.services.commands.chat import (
    ChannelMessagePersistenceWork,
    PrivateMessagePersistenceWork,
)


class StubTask:
    """enqueue payloadを記録し,必要ならenqueue失敗を再現するtask double.

    Attributes:
        fail (bool): kiq呼び出しでRuntimeErrorを送出するか.
        calls (list[tuple[tuple[object, ...], dict[str, object]]]): 成功したenqueueの引数履歴.
    """

    def __init__(self, *, fail: bool = False) -> None:
        """失敗設定と空の呼び出し履歴でtask doubleを初期化する.

        Args:
            fail (bool): Trueの場合はenqueue失敗を再現する設定.
        """
        self.fail: bool = fail
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def kiq(self, *args: object, **kwargs: object) -> None:
        """指定payloadをenqueueするか,設定済みの失敗を送出する.

        Args:
            *args (object): taskへ渡される位置引数payload.
            **kwargs (object): taskへ渡される名前付きpayload.

        Returns:
            None: 成功時はpayloadを履歴へ記録して値を返さずに完了する.

        Raises:
            RuntimeError: failがTrueでenqueue失敗を再現する場合.
        """
        if self.fail:
            msg = "enqueue failed"
            raise RuntimeError(msg)
        self.calls.append((args, kwargs))


class StubBroker:
    """task名からtest用Taskiq taskを解決するbroker double.

    Attributes:
        tasks (dict[str, StubTask]): task名ごとに遅延生成したtask double.
        missing_tasks (set[str]): 未登録としてNoneを返すtask名.
    """

    def __init__(self, *, missing_tasks: set[str] | None = None) -> None:
        """未登録taskの設定を受け取りbroker doubleを初期化する.

        Args:
            missing_tasks (set[str] | None): Noneを返すtask名. Noneなら空集合を使う.
        """
        self.tasks: dict[str, StubTask] = {}
        self.missing_tasks: set[str] = missing_tasks or set()

    def find_task(self, task_name: str) -> StubTask | None:
        """task名に対応するtaskを返すか,未登録状態を返す.

        Args:
            task_name (str): publisherが解決を試みるTaskiq task名.

        Returns:
            StubTask | None: task double. 未登録として設定したtask名ではNone.
        """
        if task_name in self.missing_tasks:
            return None
        task = self.tasks.get(task_name)
        if task is None:
            task = StubTask()
            self.tasks[task_name] = task
        return task


async def test_publish_channel_message_enqueues_existing_task_payload() -> None:
    """Channel message workを既存taskのprimitive payloadへ変換することを検証する.

    Returns:
        None: sender,channel,contentを順序どおりenqueueした履歴を確認して完了する.
    """
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
    """Private message workを既存taskのprimitive payloadへ変換することを検証する.

    Returns:
        None: senderとtargetを含むpayloadを順序どおりenqueueした履歴を確認して完了する.
    """
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
    """未登録channel taskを呼び出し側へ送出せずerror logで報告することを検証する.

    Returns:
        None: task名とsender IDを含む未登録eventが記録されることを確認して完了する.
    """
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
    """Private taskのenqueue失敗を呼び出し側へ送出せずerror logで報告することを検証する.

    Returns:
        None: task名とsender IDを含むenqueue failure eventが記録されることを確認して完了する.
    """
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

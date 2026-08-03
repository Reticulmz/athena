"""Taskiq chat persistence job adapterとjob登録契約を検証する."""

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
    """channel persistence commandを記録して成功を返すuse case stubを表す.

    Attributes:
        channel_calls (list[tuple[int, str, str]]): sender IDとchannel名とcontentの実行記録.
    """

    channel_calls: list[tuple[int, str, str]]

    def __init__(self) -> None:
        """空のchannel persistence記録でstubを初期化する."""
        self.channel_calls = []

    async def execute(self, command: PersistChannelMessageCommand) -> ChatPersistenceResult:
        """Channel persistence commandを記録して成功結果を返す.

        Args:
            command (PersistChannelMessageCommand): task adapterが変換した保存command.

        Returns:
            ChatPersistenceResult: task成功を表す固定の成功結果.
        """
        self.channel_calls.append((command.sender_id, command.channel_name, command.content))
        return ChatPersistenceResult.success_result()


class StubPrivateMessagePersistenceUseCase:
    """private persistence commandを記録して成功を返すuse case stubを表す.

    Attributes:
        private_calls (list[tuple[int, int, str]]): sender IDとtarget IDとcontentの実行記録.
    """

    private_calls: list[tuple[int, int, str]]

    def __init__(self) -> None:
        """空のprivate persistence記録でstubを初期化する."""
        self.private_calls = []

    async def execute(self, command: PersistPrivateMessageCommand) -> ChatPersistenceResult:
        """Private persistence commandを記録して成功結果を返す.

        Args:
            command (PersistPrivateMessageCommand): task adapterが変換した保存command.

        Returns:
            ChatPersistenceResult: task成功を表す固定の成功結果.
        """
        self.private_calls.append((command.sender_id, command.target_id, command.content))
        return ChatPersistenceResult.success_result()


def make_context(
    *,
    channel_use_case: object | None = None,
    private_use_case: object | None = None,
) -> Context:
    """任意のchat persistence use caseを持つTaskiq Contextを生成する.

    Args:
        channel_use_case (object | None): broker stateへ設定するchannel persistence use case.
        private_use_case (object | None): broker stateへ設定するprivate persistence use case.

    Returns:
        Context: job adapterがruntime dependencyを取得できるtest context.
    """
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
    """channel message task adapterの委譲とfailure logを検証する."""

    async def test_delegates_to_channel_persistence_use_case(self) -> None:
        """Channel taskがpayloadをuse case commandへ委譲する契約を検証する.

        channel use case stubを持つcontextでtaskを実行する.
        sender IDとchannel名とcontentがstub記録へ同順で渡ることを確認する.

        Returns:
            None: command委譲を検証して完了し,呼び出し側へ値を返さない.
        """
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
        """Channel runtime stateがない場合にerror logとRuntimeErrorを出す契約を検証する.

        use case未設定のcontextでtaskを実行する.
        RuntimeErrorとtask名とchannel情報を持つerror logが1件出ることを確認する.

        Returns:
            None: failure logの構造を検証して完了し,呼び出し側へ値を返さない.
        """
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
    """private message task adapterの委譲とfailure logを検証する."""

    async def test_delegates_to_private_persistence_use_case(self) -> None:
        """Private taskがpayloadをuse case commandへ委譲する契約を検証する.

        private use case stubを持つcontextでtaskを実行する.
        sender IDとtarget IDとcontentがstub記録へ同順で渡ることを確認する.

        Returns:
            None: command委譲を検証して完了し,呼び出し側へ値を返さない.
        """
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
        """Private runtime stateがない場合にerror logとRuntimeErrorを出す契約を検証する.

        use case未設定のcontextでtaskを実行する.
        RuntimeErrorとtask名とsenderとtargetを持つerror logが1件出ることを確認する.

        Returns:
            None: failure logの構造を検証して完了し,呼び出し側へ値を返さない.
        """
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
    """register_all_jobsが既にload済みのbrokerへ全taskを接続する契約を検証する.

    空のInMemoryBrokerでjob登録を実行し,chatとbeatmapとscoreとreplayの全task名がfind_taskで取得できることを確認する.

    Returns:
        None: brokerのtask登録を検証して完了し,呼び出し側へ値を返さない.
    """
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
    """新規processでもregister_all_jobsが必要taskをimportして接続する契約を検証する.

    Python subprocessで新しいbrokerを作ってjob登録を実行する.
    全taskが取得可能なassert scriptのexit codeが0となることを確認する.

    Returns:
        None: fresh processのjob登録を検証して完了し,呼び出し側へ値を返さない.
    """
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
    """Chat persistence jobがqueue adapter境界を越えてinfrastructureへ依存しない契約を検証する.

    job module sourceを取得する.
    SQLAlchemy repositoryとlegacy serviceのimport文字列が存在しないことを確認する.

    Returns:
        None: adapter boundaryを検証して完了し,呼び出し側へ値を返さない.
    """
    source = inspect.getsource(chat_persistence)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories.sqlalchemy" not in source
    assert "ChannelService" not in source
    assert "CommandService" not in source

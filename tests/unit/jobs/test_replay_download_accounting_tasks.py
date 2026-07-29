"""Replay download accountingのTaskiq adapterを検証するunit testを提供する."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import TYPE_CHECKING, final

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs import replay_download_accounting
from osu_server.jobs.replay_download_accounting import (
    TaskiqReplayDownloadAccountingPublisher,
    account_replay_download,
    get_replay_download_accounting_executor,
)
from osu_server.services.commands.scores import (
    LatestActivityAccountingOutcome,
    ReplayDownloadAccountingInput,
    ReplayDownloadAccountingResult,
    ReplayViewAccountingOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_OCCURRED_AT = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


class _FakeAccountingExecutor:
    """Replay download accounting use-caseの入力を記録するtest double.

    Attributes:
        inputs (list[ReplayDownloadAccountingInput]): executeへ渡されたaccounting入力の履歴.
    """

    inputs: list[ReplayDownloadAccountingInput]

    def __init__(self) -> None:
        """空の入力履歴を持つexecutor doubleを初期化する."""
        self.inputs = []

    async def execute(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> ReplayDownloadAccountingResult:
        """accounting入力を記録して成功結果を返す.

        Args:
            input_data (ReplayDownloadAccountingInput): task adapterが構築したaccounting入力.

        Returns:
            ReplayDownloadAccountingResult: replay viewとlatest activityを更新した成功結果.
        """
        self.inputs.append(input_data)
        return ReplayDownloadAccountingResult(
            replay_view_outcome=ReplayViewAccountingOutcome.INCREMENTED,
            latest_activity_outcome=LatestActivityAccountingOutcome.TOUCHED,
        )


@final
class _StubTask:
    """enqueue payloadを記録し,設定した例外を再現するTaskiq task double.

    Attributes:
        calls (list[tuple[tuple[object, ...], dict[str, object]]]): kiqへ渡されたpayload履歴.
        _error (Exception | None): enqueue時に送出する例外. Noneなら成功する.
    """

    calls: list[tuple[tuple[object, ...], dict[str, object]]]
    _error: Exception | None

    def __init__(self, *, error: Exception | None = None) -> None:
        """enqueue失敗の有無と空のpayload履歴を設定する.

        Args:
            error (Exception | None): kiqで送出する例外. Noneなら正常に完了する.
        """
        self.calls = []
        self._error = error

    async def kiq(self, *args: object, **kwargs: object) -> object:
        """payloadを記録して成功objectを返すか,設定済み例外を送出する.

        Args:
            *args (object): taskへ渡される位置引数payload.
            **kwargs (object): taskへ渡される名前付きpayload.

        Returns:
            object: enqueue成功を表す新しいobject.

        Raises:
            Exception: _errorに設定したenqueue失敗を再現する場合.
        """
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        return object()


@final
class _StubBroker:
    """指定taskを返し,lookupしたtask名を記録するbroker double.

    Attributes:
        _task (_StubTask | None): lookup時に返すtask. Noneは未登録を表す.
        task_names (list[str]): find_taskへ渡されたtask名の履歴.
    """

    _task: _StubTask | None
    task_names: list[str]

    def __init__(self, task: _StubTask | None) -> None:
        """lookup結果に使うtask doubleを初期化する.

        Args:
            task (_StubTask | None): 返すtask. Noneなら未登録状態を再現する.
        """
        self._task = task
        self.task_names = []

    def find_task(self, task_name: str) -> _StubTask | None:
        """task名を記録して設定済みtaskを返す.

        Args:
            task_name (str): publisherが解決を試みるtask名.

        Returns:
            _StubTask | None: 設定済みtask,または未登録を表すNone.
        """
        self.task_names.append(task_name)
        return self._task


def _make_context(**services: object) -> Context:
    """指定serviceをTaskiq stateに登録したtest contextを構築する.

    Args:
        **services (object): state属性名と登録するexecutor doubleの対応.

    Returns:
        Context: account_replay_downloadを実行できるTaskiq context.
    """
    broker = InMemoryBroker()
    for key, value in services.items():
        object.__setattr__(broker.state, key, value)
    message = TaskiqMessage(
        task_id="replay-accounting-test-task",
        task_name="account_replay_download",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


def test_replay_download_accounting_task_is_registered() -> None:
    """account_replay_download taskがjobs registryへ登録されることを検証する.

    Returns:
        None: task名がregistryに存在することを確認して完了する.
    """
    assert "account_replay_download" in jobs.task_names


def test_replay_download_accounting_job_stays_queue_adapter_only() -> None:
    """Accounting jobがrepositoryや低水準infrastructureへ依存しないことを検証する.

    Returns:
        None: sourceにSQLAlchemy,repository,Valkey参照がないことを確認して完了する.
    """
    source = inspect.getsource(replay_download_accounting)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories" not in source
    assert "Valkey" not in source


async def test_publisher_enqueues_primitive_payload() -> None:
    """publisherがaccounting入力をprimitive Taskiq payloadへ変換することを検証する.

    Returns:
        None: ID群とISO 8601時刻を順序どおりenqueueした履歴を確認して完了する.
    """
    task = _StubTask()
    broker = _StubBroker(task)
    publisher = TaskiqReplayDownloadAccountingPublisher(broker)

    await publisher.publish(
        ReplayDownloadAccountingInput(
            score_id=515,
            score_owner_user_id=616,
            viewer_user_id=42,
            occurred_at=_OCCURRED_AT,
        )
    )

    assert broker.task_names == ["account_replay_download"]
    assert task.calls == [((515, 616, 42, _OCCURRED_AT.isoformat()), {})]


async def test_publisher_logs_missing_task_without_raising() -> None:
    """未登録taskを呼び出し側へ送出せず構造化error logへ記録することを検証する.

    Returns:
        None: task名,score ID,viewer IDを含む未登録eventを確認して完了する.
    """
    broker = _StubBroker(None)
    publisher = TaskiqReplayDownloadAccountingPublisher(broker)

    with structlog.testing.capture_logs() as logs:
        await publisher.publish(
            ReplayDownloadAccountingInput(
                score_id=515,
                score_owner_user_id=616,
                viewer_user_id=42,
                occurred_at=_OCCURRED_AT,
            )
        )

    entries = _entries(logs, "replay_download_accounting_task_not_registered")
    assert len(entries) == 1
    assert entries[0]["task_name"] == "account_replay_download"
    assert entries[0]["score_id"] == 515
    assert entries[0]["viewer_user_id"] == 42
    assert entries[0]["log_level"] == "error"


async def test_publisher_logs_enqueue_failure_without_raising() -> None:
    """enqueue失敗を呼び出し側へ送出せず構造化error logへ記録することを検証する.

    Returns:
        None: task名,score ID,viewer IDを含むfailure eventを確認して完了する.
    """
    broker = _StubBroker(_StubTask(error=RuntimeError("broker unavailable")))
    publisher = TaskiqReplayDownloadAccountingPublisher(broker)

    with structlog.testing.capture_logs() as logs:
        await publisher.publish(
            ReplayDownloadAccountingInput(
                score_id=515,
                score_owner_user_id=616,
                viewer_user_id=42,
                occurred_at=_OCCURRED_AT,
            )
        )

    entries = _entries(logs, "replay_download_accounting_enqueue_failed")
    assert len(entries) == 1
    assert entries[0]["task_name"] == "account_replay_download"
    assert entries[0]["score_id"] == 515
    assert entries[0]["viewer_user_id"] == 42
    assert entries[0]["log_level"] == "error"


async def test_task_delegates_to_replay_download_accounting_use_case() -> None:
    """taskがprimitive payloadをaccounting入力へ復元してexecutorへ委譲することを検証する.

    Returns:
        None: ID群とUTC時刻を復元した入力がexecutorへ1回渡ることを確認して完了する.
    """
    executor = _FakeAccountingExecutor()
    context = _make_context(replay_download_accounting_executor=executor)

    await account_replay_download(
        score_id=515,
        score_owner_user_id=616,
        viewer_user_id=42,
        occurred_at_iso=_OCCURRED_AT.isoformat(),
        context=context,
    )

    assert executor.inputs == [
        ReplayDownloadAccountingInput(
            score_id=515,
            score_owner_user_id=616,
            viewer_user_id=42,
            occurred_at=_OCCURRED_AT,
        )
    ]


async def test_task_raises_when_runtime_state_is_missing() -> None:
    """executor未登録時にtaskが例外とruntime unavailable logを残すことを検証する.

    Returns:
        None: task名,score ID,viewer IDを含むerror eventを確認して完了する.
    """
    context = _make_context()

    with (
        structlog.testing.capture_logs() as logs,
        pytest.raises(
            RuntimeError,
            match="replay download accounting use-case is not registered",
        ),
    ):
        await account_replay_download(
            score_id=515,
            score_owner_user_id=616,
            viewer_user_id=42,
            occurred_at_iso=_OCCURRED_AT.isoformat(),
            context=context,
        )

    entries = _entries(logs, "replay_download_accounting_runtime_unavailable")
    assert len(entries) == 1
    assert entries[0]["task_name"] == "account_replay_download"
    assert entries[0]["score_id"] == 515
    assert entries[0]["viewer_user_id"] == 42
    assert entries[0]["log_level"] == "error"


async def test_task_rejects_invalid_occurred_at_payload() -> None:
    """不正なISO時刻payloadをexecutor実行前に拒否することを検証する.

    Returns:
        None: ValueError,空のexecutor入力,invalid field logを確認して完了する.
    """
    executor = _FakeAccountingExecutor()
    context = _make_context(replay_download_accounting_executor=executor)

    with (
        structlog.testing.capture_logs() as logs,
        pytest.raises(
            ValueError,
            match="Invalid isoformat string",
        ),
    ):
        await account_replay_download(
            score_id=515,
            score_owner_user_id=616,
            viewer_user_id=42,
            occurred_at_iso="not-a-datetime",
            context=context,
        )

    assert executor.inputs == []
    entries = _entries(logs, "replay_download_accounting_payload_invalid")
    assert len(entries) == 1
    assert entries[0]["task_name"] == "account_replay_download"
    assert entries[0]["field"] == "occurred_at_iso"
    assert entries[0]["log_level"] == "error"


def test_getter_returns_executor_from_taskiq_state() -> None:
    """登録済みaccounting executorをstate getterが同一instanceで返すことを検証する.

    Returns:
        None: stateへ登録したexecutorとgetter結果が同一であることを確認する.
    """
    executor = _FakeAccountingExecutor()
    state = TaskiqState()
    object.__setattr__(state, "replay_download_accounting_executor", executor)

    result = get_replay_download_accounting_executor(state)

    assert result is executor


def test_getter_returns_none_when_missing() -> None:
    """Accounting executor未登録時にstate getterがNoneを返すことを検証する.

    Returns:
        None: 空のstateからのgetter結果がNoneであることを確認する.
    """
    state = TaskiqState()

    result = get_replay_download_accounting_executor(state)

    assert result is None


def _entries(
    logs: Sequence[Mapping[str, object]],
    event: str,
) -> list[Mapping[str, object]]:
    """captureしたlogから指定eventだけを抽出する.

    Args:
        logs (Sequence[Mapping[str, object]]): structlog captureが返すevent列.
        event (str): 抽出対象のevent名.

    Returns:
        list[Mapping[str, object]]: event名が一致するlog entryの順序を保った列.
    """
    return [entry for entry in logs if entry.get("event") == event]

"""Replay download accounting taskiq job adapter tests."""

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
    """Replay download accounting use-case のテストダブル。"""

    inputs: list[ReplayDownloadAccountingInput]

    def __init__(self) -> None:
        self.inputs = []

    async def execute(
        self,
        input_data: ReplayDownloadAccountingInput,
    ) -> ReplayDownloadAccountingResult:
        self.inputs.append(input_data)
        return ReplayDownloadAccountingResult(
            replay_view_outcome=ReplayViewAccountingOutcome.INCREMENTED,
            latest_activity_outcome=LatestActivityAccountingOutcome.TOUCHED,
        )


@final
class _StubTask:
    """Taskiq task のテストダブル。"""

    calls: list[tuple[tuple[object, ...], dict[str, object]]]
    _error: Exception | None

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = []
        self._error = error

    async def kiq(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        return object()


@final
class _StubBroker:
    """Task lookup のテストダブル。"""

    _task: _StubTask | None
    task_names: list[str]

    def __init__(self, task: _StubTask | None) -> None:
        self._task = task
        self.task_names = []

    def find_task(self, task_name: str) -> _StubTask | None:
        self.task_names.append(task_name)
        return self._task


def _make_context(**services: object) -> Context:
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
    assert "account_replay_download" in jobs.task_names


def test_replay_download_accounting_job_stays_queue_adapter_only() -> None:
    source = inspect.getsource(replay_download_accounting)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories" not in source
    assert "Valkey" not in source


async def test_publisher_enqueues_primitive_payload() -> None:
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
    executor = _FakeAccountingExecutor()
    state = TaskiqState()
    object.__setattr__(state, "replay_download_accounting_executor", executor)

    result = get_replay_download_accounting_executor(state)

    assert result is executor


def test_getter_returns_none_when_missing() -> None:
    state = TaskiqState()

    result = get_replay_download_accounting_executor(state)

    assert result is None


def _entries(
    logs: Sequence[Mapping[str, object]],
    event: str,
) -> list[Mapping[str, object]]:
    return [entry for entry in logs if entry.get("event") == event]

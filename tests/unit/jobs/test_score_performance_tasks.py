"""Tests for score performance taskiq job adapters."""

from __future__ import annotations

import inspect
from datetime import UTC
from typing import TYPE_CHECKING, final

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs import score_performance
from osu_server.jobs.score_performance import (
    TaskiqPerformanceCalculationWorkerWake,
    calculate_score_performance,
    get_performance_recalculation_batch_processor,
    get_score_performance_calculation_executor,
    process_performance_recalculation_batch,
)
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationOutcome,
    ExecutePerformanceCalculationResult,
)

if TYPE_CHECKING:
    from osu_server.services.commands.scores.performance import (
        ExecutePerformanceCalculationCommand,
    )


class _FakeCalculationExecutor:
    calls: list[ExecutePerformanceCalculationCommand]

    def __init__(self) -> None:
        self.calls = []

    async def execute(
        self,
        command: ExecutePerformanceCalculationCommand,
    ) -> ExecutePerformanceCalculationResult:
        self.calls.append(command)
        return ExecutePerformanceCalculationResult(
            outcome=ExecutePerformanceCalculationOutcome.CLAIM_NOT_ACQUIRED,
            calculation_id=command.calculation_id,
        )


class _FakeBatchProcessor:
    calls: list[int]

    def __init__(self) -> None:
        self.calls = []

    async def execute(self, batch_id: int) -> None:
        self.calls.append(batch_id)


@final
class _FakeEnqueueableTask:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def kiq(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        return object()


@final
class _FakeBroker:
    def __init__(self, task: _FakeEnqueueableTask | None) -> None:
        self._task = task
        self.task_names: list[str] = []

    def find_task(self, task_name: str) -> _FakeEnqueueableTask | None:
        self.task_names.append(task_name)
        return self._task


def _make_context(**services: object) -> Context:
    broker = InMemoryBroker()
    for key, value in services.items():
        object.__setattr__(broker.state, key, value)
    message = TaskiqMessage(
        task_id="score-performance-test-task",
        task_name="test",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


class TestScorePerformanceTaskRegistration:
    def test_calculation_task_is_registered(self) -> None:
        assert "calculate_score_performance" in jobs.task_names

    def test_recalculation_batch_task_is_registered(self) -> None:
        assert "process_performance_recalculation_batch" in jobs.task_names


def test_score_performance_job_stays_queue_adapter_only() -> None:
    source = inspect.getsource(score_performance)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories" not in source
    assert "Valkey" not in source
    assert "RosuPerformanceCalculator" not in source
    assert "RosuPerformanceCalculator(" not in source


class TestScorePerformanceTaskRuntimeUnavailable:
    async def test_calculation_task_raises_when_runtime_missing(self) -> None:
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="score performance calculation use-case is not registered",
            ),
        ):
            await calculate_score_performance(
                score_id=123,
                calculation_id=456,
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "score_performance_calculation_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "calculate_score_performance"
        assert entries[0]["score_id"] == 123
        assert entries[0]["calculation_id"] == 456
        assert entries[0]["log_level"] == "error"

    async def test_recalculation_batch_task_raises_when_runtime_missing(self) -> None:
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="performance recalculation batch use-case is not registered",
            ),
        ):
            await process_performance_recalculation_batch(
                batch_id=789,
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "performance_recalculation_batch_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "process_performance_recalculation_batch"
        assert entries[0]["batch_id"] == 789
        assert entries[0]["log_level"] == "error"

    async def test_calculation_task_does_not_call_wrong_runtime_state(self) -> None:
        fake = _FakeCalculationExecutor()
        context = _make_context(wrong_key=fake)

        with pytest.raises(RuntimeError):
            await calculate_score_performance(
                score_id=123,
                calculation_id=456,
                context=context,
            )

        assert fake.calls == []

    async def test_recalculation_batch_task_does_not_call_wrong_runtime_state(self) -> None:
        fake = _FakeBatchProcessor()
        context = _make_context(wrong_key=fake)

        with pytest.raises(RuntimeError):
            await process_performance_recalculation_batch(batch_id=789, context=context)

        assert fake.calls == []


class TestScorePerformanceTaskExecution:
    async def test_calculation_task_delegates_to_executor_with_command(self) -> None:
        fake = _FakeCalculationExecutor()
        context = _make_context(score_performance_calculation_executor=fake)

        await calculate_score_performance(
            score_id=123,
            calculation_id=456,
            context=context,
        )

        assert len(fake.calls) == 1
        command = fake.calls[0]
        assert command.calculation_id == 456
        assert command.claim_owner == "taskiq:score-performance-test-task"
        assert command.claimed_at.tzinfo is UTC

    async def test_recalculation_batch_task_delegates_to_processor(self) -> None:
        fake = _FakeBatchProcessor()
        context = _make_context(performance_recalculation_batch_processor=fake)

        await process_performance_recalculation_batch(batch_id=789, context=context)

        assert fake.calls == [789]


class TestTaskiqPerformanceCalculationWorkerWake:
    async def test_wake_enqueues_calculation_task_with_primitive_ids(self) -> None:
        task = _FakeEnqueueableTask()
        broker = _FakeBroker(task)
        wake = TaskiqPerformanceCalculationWorkerWake(broker)

        await wake.wake_score_calculation(score_id=123, calculation_id=456)

        assert broker.task_names == ["calculate_score_performance"]
        assert task.calls == [((123, 456), {})]

    async def test_wake_raises_and_logs_when_task_is_not_registered(self) -> None:
        broker = _FakeBroker(None)
        wake = TaskiqPerformanceCalculationWorkerWake(broker)

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="score performance calculation task is not registered",
            ),
        ):
            await wake.wake_score_calculation(score_id=123, calculation_id=456)

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "score_performance_calculation_task_not_registered"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "calculate_score_performance"
        assert entries[0]["score_id"] == 123
        assert entries[0]["calculation_id"] == 456
        assert entries[0]["log_level"] == "error"

    async def test_wake_raises_and_logs_when_enqueue_fails(self) -> None:
        task = _FakeEnqueueableTask(error=RuntimeError("broker unavailable"))
        broker = _FakeBroker(task)
        wake = TaskiqPerformanceCalculationWorkerWake(broker)

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(RuntimeError, match="broker unavailable"),
        ):
            await wake.wake_score_calculation(score_id=123, calculation_id=456)

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "score_performance_calculation_enqueue_failed"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "calculate_score_performance"
        assert entries[0]["score_id"] == 123
        assert entries[0]["calculation_id"] == 456
        assert entries[0]["log_level"] == "error"


class TestScorePerformanceStateGetters:
    def test_calculation_executor_getter_returns_service(self) -> None:
        fake = _FakeCalculationExecutor()
        state = TaskiqState()
        object.__setattr__(state, "score_performance_calculation_executor", fake)

        result = get_score_performance_calculation_executor(state)

        assert result is fake

    def test_calculation_executor_getter_returns_none_when_missing(self) -> None:
        state = TaskiqState()

        result = get_score_performance_calculation_executor(state)

        assert result is None

    def test_recalculation_batch_processor_getter_returns_service(self) -> None:
        fake = _FakeBatchProcessor()
        state = TaskiqState()
        object.__setattr__(state, "performance_recalculation_batch_processor", fake)

        result = get_performance_recalculation_batch_processor(state)

        assert result is fake

    def test_recalculation_batch_processor_getter_returns_none_when_missing(self) -> None:
        state = TaskiqState()

        result = get_performance_recalculation_batch_processor(state)

        assert result is None

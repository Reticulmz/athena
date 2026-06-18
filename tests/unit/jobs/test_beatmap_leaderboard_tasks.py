"""Tests for Beatmap Leaderboard rebuild taskiq job adapters."""

from __future__ import annotations

import inspect
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs import beatmap_leaderboards, register_all_jobs
from osu_server.jobs.beatmap_leaderboards import (
    TaskiqBeatmapLeaderboardRebuildWorkerWake,
    get_beatmap_leaderboard_beatmapset_rebuild_use_case,
    get_beatmap_leaderboard_user_rebuild_use_case,
    rebuild_beatmap_leaderboards_for_beatmapset,
    rebuild_beatmap_leaderboards_for_user,
)
from osu_server.services.commands.scores.leaderboards import RebuildBeatmapLeaderboardsResult

if TYPE_CHECKING:
    from osu_server.services.commands.scores.leaderboards import (
        RebuildBeatmapLeaderboardsForBeatmapsetCommand,
        RebuildBeatmapLeaderboardsForUserCommand,
    )


class _FakeUserRebuildUseCase:
    calls: list[RebuildBeatmapLeaderboardsForUserCommand]
    _result: RebuildBeatmapLeaderboardsResult | None
    _error: Exception | None

    def __init__(
        self,
        *,
        result: RebuildBeatmapLeaderboardsResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls = []
        self._result = result
        self._error = error

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForUserCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        self.calls.append(command)
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        return RebuildBeatmapLeaderboardsResult(
            target_found=True,
            source_score_count=2,
            projection_row_count=3,
        )


class _FakeBeatmapsetRebuildUseCase:
    calls: list[RebuildBeatmapLeaderboardsForBeatmapsetCommand]
    _result: RebuildBeatmapLeaderboardsResult | None
    _error: Exception | None

    def __init__(
        self,
        *,
        result: RebuildBeatmapLeaderboardsResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls = []
        self._result = result
        self._error = error

    async def execute(
        self,
        command: RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    ) -> RebuildBeatmapLeaderboardsResult:
        self.calls.append(command)
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        return RebuildBeatmapLeaderboardsResult(
            target_found=True,
            source_score_count=4,
            projection_row_count=5,
        )


def _make_context(**services: object) -> Context:
    broker = InMemoryBroker()
    for key, value in services.items():
        object.__setattr__(broker.state, key, value)
    message = TaskiqMessage(
        task_id="beatmap-leaderboard-test-task",
        task_name="test",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


class _FakeEnqueueableTask:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error: Exception | None = error
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def kiq(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error
        return object()


class _FakeBroker:
    def __init__(self, task: _FakeEnqueueableTask | None) -> None:
        self._task: _FakeEnqueueableTask | None = task
        self.task_names: list[str] = []

    def find_task(self, task_name: str) -> _FakeEnqueueableTask | None:
        self.task_names.append(task_name)
        return self._task


class TestBeatmapLeaderboardTaskRegistration:
    def test_user_rebuild_task_is_registered(self) -> None:
        assert "rebuild_beatmap_leaderboards_for_user" in jobs.task_names

    def test_beatmapset_rebuild_task_is_registered(self) -> None:
        assert "rebuild_beatmap_leaderboards_for_beatmapset" in jobs.task_names

    def test_register_all_jobs_attaches_rebuild_tasks_to_broker(self) -> None:
        broker = InMemoryBroker()

        register_all_jobs(broker)

        assert broker.find_task("rebuild_beatmap_leaderboards_for_user") is not None
        assert broker.find_task("rebuild_beatmap_leaderboards_for_beatmapset") is not None

    def test_register_all_jobs_loads_rebuild_tasks_in_fresh_process(self) -> None:
        code = """
from taskiq import InMemoryBroker
from osu_server.jobs import register_all_jobs

broker = InMemoryBroker()
register_all_jobs(broker)
assert broker.find_task("rebuild_beatmap_leaderboards_for_user") is not None
assert broker.find_task("rebuild_beatmap_leaderboards_for_beatmapset") is not None
"""

        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr


def test_beatmap_leaderboard_job_stays_queue_adapter_only() -> None:
    source = inspect.getsource(beatmap_leaderboards)

    assert "sqlalchemy" not in source
    assert "osu_server.repositories" not in source
    assert "Valkey" not in source


class TestBeatmapLeaderboardTaskRuntimeUnavailable:
    async def test_user_rebuild_task_raises_when_runtime_missing(self) -> None:
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="Beatmap Leaderboard user rebuild use-case is not registered",
            ),
        ):
            await rebuild_beatmap_leaderboards_for_user(
                user_id=1000,
                reason="visibility_changed",
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_leaderboard_rebuild_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "rebuild_beatmap_leaderboards_for_user"
        assert entries[0]["target_kind"] == "user"
        assert entries[0]["user_id"] == 1000
        assert entries[0]["log_level"] == "error"

    async def test_beatmapset_rebuild_task_raises_when_runtime_missing(self) -> None:
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="Beatmap Leaderboard beatmapset rebuild use-case is not registered",
            ),
        ):
            await rebuild_beatmap_leaderboards_for_beatmapset(
                beatmapset_id=2000,
                reason="beatmap_checksum_changed",
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_leaderboard_rebuild_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "rebuild_beatmap_leaderboards_for_beatmapset"
        assert entries[0]["target_kind"] == "beatmapset"
        assert entries[0]["beatmapset_id"] == 2000
        assert entries[0]["log_level"] == "error"

    async def test_user_rebuild_task_does_not_call_wrong_runtime_state(self) -> None:
        fake = _FakeUserRebuildUseCase()
        context = _make_context(wrong_key=fake)

        with pytest.raises(RuntimeError):
            await rebuild_beatmap_leaderboards_for_user(
                user_id=1000,
                reason="visibility_changed",
                context=context,
            )

        assert fake.calls == []

    async def test_beatmapset_rebuild_task_does_not_call_wrong_runtime_state(self) -> None:
        fake = _FakeBeatmapsetRebuildUseCase()
        context = _make_context(wrong_key=fake)

        with pytest.raises(RuntimeError):
            await rebuild_beatmap_leaderboards_for_beatmapset(
                beatmapset_id=2000,
                reason="beatmap_checksum_changed",
                context=context,
            )

        assert fake.calls == []


class TestBeatmapLeaderboardTaskPayloadValidation:
    async def test_user_rebuild_rejects_non_int_user_id(self) -> None:
        fake = _FakeUserRebuildUseCase()
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            await rebuild_beatmap_leaderboards_for_user(
                user_id="1000",
                reason="visibility_changed",
                context=context,
            )

        assert fake.calls == []

    async def test_user_rebuild_rejects_bool_user_id(self) -> None:
        fake = _FakeUserRebuildUseCase()
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            await rebuild_beatmap_leaderboards_for_user(
                user_id=True,
                reason="visibility_changed",
                context=context,
            )

        assert fake.calls == []

    async def test_beatmapset_rebuild_rejects_empty_reason(self) -> None:
        fake = _FakeBeatmapsetRebuildUseCase()
        context = _make_context(beatmap_leaderboard_beatmapset_rebuild_use_case=fake)

        with pytest.raises(ValueError, match="reason must be a non-empty string"):
            await rebuild_beatmap_leaderboards_for_beatmapset(
                beatmapset_id=2000,
                reason="",
                context=context,
            )

        assert fake.calls == []


class TestBeatmapLeaderboardTaskExecution:
    async def test_user_rebuild_task_delegates_with_command(self) -> None:
        fake = _FakeUserRebuildUseCase()
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        await rebuild_beatmap_leaderboards_for_user(
            user_id=1000,
            reason="visibility_changed",
            context=context,
        )

        assert len(fake.calls) == 1
        command = fake.calls[0]
        assert command.user_id == 1000
        assert command.reason == "visibility_changed"

    async def test_beatmapset_rebuild_task_delegates_with_command(self) -> None:
        fake = _FakeBeatmapsetRebuildUseCase()
        context = _make_context(beatmap_leaderboard_beatmapset_rebuild_use_case=fake)

        await rebuild_beatmap_leaderboards_for_beatmapset(
            beatmapset_id=2000,
            reason="beatmap_checksum_changed",
            context=context,
        )

        assert len(fake.calls) == 1
        command = fake.calls[0]
        assert command.beatmapset_id == 2000
        assert command.reason == "beatmap_checksum_changed"

    async def test_duplicate_user_rebuild_execution_delegates_each_job_once(self) -> None:
        fake = _FakeUserRebuildUseCase()
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        await rebuild_beatmap_leaderboards_for_user(
            user_id=1000,
            reason="visibility_changed",
            context=context,
        )
        await rebuild_beatmap_leaderboards_for_user(
            user_id=1000,
            reason="visibility_changed",
            context=context,
        )

        assert [(command.user_id, command.reason) for command in fake.calls] == [
            (1000, "visibility_changed"),
            (1000, "visibility_changed"),
        ]

    async def test_beatmapset_missing_target_is_noop_success(self) -> None:
        fake = _FakeBeatmapsetRebuildUseCase(
            result=RebuildBeatmapLeaderboardsResult(
                target_found=False,
                source_score_count=0,
                projection_row_count=0,
            )
        )
        context = _make_context(beatmap_leaderboard_beatmapset_rebuild_use_case=fake)

        with structlog.testing.capture_logs() as logs:
            await rebuild_beatmap_leaderboards_for_beatmapset(
                beatmapset_id=404,
                reason="beatmap_status_changed",
                context=context,
            )

        assert len(fake.calls) == 1
        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_leaderboard_rebuild_completed"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "rebuild_beatmap_leaderboards_for_beatmapset"
        assert entries[0]["target_kind"] == "beatmapset"
        assert entries[0]["target_found"] is False
        assert entries[0]["log_level"] == "info"

    async def test_persistence_failure_surfaces(self) -> None:
        fake = _FakeUserRebuildUseCase(error=RuntimeError("database unavailable"))
        context = _make_context(beatmap_leaderboard_user_rebuild_use_case=fake)

        with pytest.raises(RuntimeError, match="database unavailable"):
            await rebuild_beatmap_leaderboards_for_user(
                user_id=1000,
                reason="visibility_changed",
                context=context,
            )

        assert len(fake.calls) == 1


class TestBeatmapLeaderboardStateGetters:
    def test_user_rebuild_getter_returns_service(self) -> None:
        fake = _FakeUserRebuildUseCase()
        state = TaskiqState()
        object.__setattr__(state, "beatmap_leaderboard_user_rebuild_use_case", fake)

        result = get_beatmap_leaderboard_user_rebuild_use_case(state)

        assert result is fake

    def test_user_rebuild_getter_returns_none_when_missing(self) -> None:
        state = TaskiqState()

        result = get_beatmap_leaderboard_user_rebuild_use_case(state)

        assert result is None

    def test_beatmapset_rebuild_getter_returns_service(self) -> None:
        fake = _FakeBeatmapsetRebuildUseCase()
        state = TaskiqState()
        object.__setattr__(state, "beatmap_leaderboard_beatmapset_rebuild_use_case", fake)

        result = get_beatmap_leaderboard_beatmapset_rebuild_use_case(state)

        assert result is fake

    def test_beatmapset_rebuild_getter_returns_none_when_missing(self) -> None:
        state = TaskiqState()

        result = get_beatmap_leaderboard_beatmapset_rebuild_use_case(state)

        assert result is None


class TestTaskiqBeatmapLeaderboardRebuildWorkerWake:
    async def test_wake_user_rebuild_enqueues_primitive_payload(self) -> None:
        task = _FakeEnqueueableTask()
        broker = _FakeBroker(task)
        wake = TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

        await wake.wake_user_rebuild(user_id=1000, reason="user_visibility_changed")

        assert broker.task_names == ["rebuild_beatmap_leaderboards_for_user"]
        assert task.calls == [((1000, "user_visibility_changed"), {})]

    async def test_wake_beatmapset_rebuild_enqueues_primitive_payload(self) -> None:
        task = _FakeEnqueueableTask()
        broker = _FakeBroker(task)
        wake = TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

        await wake.wake_beatmapset_rebuild(
            beatmapset_id=2000,
            reason="beatmap_checksum_changed",
        )

        assert broker.task_names == ["rebuild_beatmap_leaderboards_for_beatmapset"]
        assert task.calls == [((2000, "beatmap_checksum_changed"), {})]

    async def test_wake_raises_when_task_is_not_registered(self) -> None:
        broker = _FakeBroker(None)
        wake = TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

        with pytest.raises(
            RuntimeError,
            match="Beatmap Leaderboard user rebuild task is not registered",
        ):
            await wake.wake_user_rebuild(user_id=1000, reason="user_visibility_changed")

    async def test_wake_surfaces_enqueue_failure(self) -> None:
        task = _FakeEnqueueableTask(error=RuntimeError("broker unavailable"))
        broker = _FakeBroker(task)
        wake = TaskiqBeatmapLeaderboardRebuildWorkerWake(broker)

        with pytest.raises(RuntimeError, match="broker unavailable"):
            await wake.wake_beatmapset_rebuild(
                beatmapset_id=2000,
                reason="beatmap_checksum_changed",
            )

"""Tests for beatmap fetch taskiq job adapters.

Covers:
- Job registry registration (task names are registered).
- Task functions resolve their service from taskiq state and delegate to execute.
- Task functions fail observably when required runtime state is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import structlog.testing
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

from osu_server.domain.beatmaps import BeatmapFetchTargetKind
from osu_server.infrastructure.jobs.registry import jobs
from osu_server.jobs.beatmap_fetch import (
    fetch_beatmap_file,
    fetch_beatmap_metadata,
    get_beatmap_file_fetch,
    get_beatmap_metadata_fetch,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import BeatmapFetchTarget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeJob:
    """Records calls so we can assert the task delegates correctly."""

    def __init__(self) -> None:
        self.calls: list[BeatmapFetchTarget] = []

    async def execute(self, target: BeatmapFetchTarget) -> None:
        self.calls.append(target)


def _make_context(**services: object) -> Context:
    """Build a taskiq ``Context`` with named services attached to state."""
    broker = InMemoryBroker()
    for key, value in services.items():
        object.__setattr__(broker.state, key, value)
    message = TaskiqMessage(
        task_id="test-task-id",
        task_name="test",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestBeatmapFetchTaskRegistration:
    """Both beatmap fetch task names are registered in the job registry."""

    def test_fetch_beatmap_metadata_is_registered(self) -> None:
        assert "fetch_beatmap_metadata" in jobs.task_names

    def test_fetch_beatmap_file_is_registered(self) -> None:
        assert "fetch_beatmap_file" in jobs.task_names


# ---------------------------------------------------------------------------
# Runtime-unavailable tests
# ---------------------------------------------------------------------------


class TestBeatmapFetchTaskRuntimeUnavailable:
    """Task functions raise and log runtime_unavailable when state is missing."""

    async def test_metadata_task_raises_when_runtime_missing(self) -> None:
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="beatmap metadata fetch use-case is not registered",
            ),
        ):
            await fetch_beatmap_metadata(
                target_type="metadata:beatmap",
                target_key="2000",
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_metadata_fetch_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "fetch_beatmap_metadata"
        assert entries[0]["target_type"] == "metadata:beatmap"
        assert entries[0]["target_key"] == "2000"
        assert entries[0]["log_level"] == "error"

    async def test_file_task_raises_when_runtime_missing(self) -> None:
        context = _make_context()

        with (
            structlog.testing.capture_logs() as logs,
            pytest.raises(
                RuntimeError,
                match="beatmap file fetch use-case is not registered",
            ),
        ):
            await fetch_beatmap_file(
                target_type="file:beatmap",
                target_key="2000",
                context=context,
            )

        entries = [
            entry
            for entry in logs
            if entry.get("event") == "beatmap_file_fetch_runtime_unavailable"
        ]
        assert len(entries) == 1
        assert entries[0]["task_name"] == "fetch_beatmap_file"
        assert entries[0]["target_type"] == "file:beatmap"
        assert entries[0]["target_key"] == "2000"
        assert entries[0]["log_level"] == "error"

    async def test_metadata_task_does_not_call_job_when_runtime_missing(self) -> None:
        """When runtime is missing, the fake job is never called."""
        fake = _FakeJob()
        # Attach the fake under a *different* key so the task does not find it.
        context = _make_context(wrong_key=fake)
        with pytest.raises(RuntimeError):
            await fetch_beatmap_metadata(
                target_type="metadata:beatmap",
                target_key="2000",
                context=context,
            )
        assert len(fake.calls) == 0

    async def test_file_task_does_not_call_job_when_runtime_missing(self) -> None:
        """When runtime is missing, the fake job is never called."""
        fake = _FakeJob()
        context = _make_context(wrong_key=fake)
        with pytest.raises(RuntimeError):
            await fetch_beatmap_file(
                target_type="file:beatmap",
                target_key="2000",
                context=context,
            )
        assert len(fake.calls) == 0


# ---------------------------------------------------------------------------
# Runtime-available tests
# ---------------------------------------------------------------------------


class TestBeatmapFetchTaskExecution:
    """Task functions resolve the service from state and delegate to execute."""

    async def test_metadata_task_delegates_to_service(self) -> None:
        fake = _FakeJob()
        context = _make_context(beatmap_metadata_fetch=fake)
        await fetch_beatmap_metadata(
            target_type="metadata:beatmap",
            target_key="2000",
            context=context,
        )
        assert len(fake.calls) == 1
        assert fake.calls[0].kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID
        assert fake.calls[0].target_key == "2000"
        assert fake.calls[0].force_refresh is False

    async def test_file_task_delegates_to_service(self) -> None:
        fake = _FakeJob()
        context = _make_context(beatmap_file_fetch=fake)
        await fetch_beatmap_file(
            target_type="file:beatmap",
            target_key="2000",
            context=context,
        )
        assert len(fake.calls) == 1
        assert fake.calls[0].kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID
        assert fake.calls[0].target_key == "2000"

    async def test_metadata_task_constructs_beatmap_fetch_target(self) -> None:
        """The task constructs a BeatmapFetchTarget from string params."""
        fake = _FakeJob()
        context = _make_context(beatmap_metadata_fetch=fake)
        await fetch_beatmap_metadata(
            target_type="metadata:checksum",
            target_key="md5:checksum-for-test",
            context=context,
        )
        assert len(fake.calls) == 1
        assert fake.calls[0].kind is BeatmapFetchTargetKind.METADATA_BY_CHECKSUM
        assert fake.calls[0].target_key == "md5:checksum-for-test"

    async def test_metadata_task_preserves_force_refresh_flag(self) -> None:
        fake = _FakeJob()
        context = _make_context(beatmap_metadata_fetch=fake)
        await fetch_beatmap_metadata(
            target_type="metadata:beatmap",
            target_key="2000",
            force_refresh=True,
            context=context,
        )

        assert len(fake.calls) == 1
        assert fake.calls[0].force_refresh is True

    async def test_file_task_constructs_beatmap_fetch_target(self) -> None:
        """The task constructs a BeatmapFetchTarget from string params."""
        fake = _FakeJob()
        context = _make_context(beatmap_file_fetch=fake)
        await fetch_beatmap_file(
            target_type="file:beatmap",
            target_key="9999",
            context=context,
        )
        assert len(fake.calls) == 1
        assert fake.calls[0].kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID
        assert fake.calls[0].target_key == "9999"


# ---------------------------------------------------------------------------
# State getter tests
# ---------------------------------------------------------------------------


class TestBeatmapFetchStateGetters:
    """The getter helpers resolve services from TaskiqState or return None."""

    def test_get_beatmap_metadata_fetch_returns_service(self) -> None:
        fake = _FakeJob()
        state = TaskiqState()
        object.__setattr__(state, "beatmap_metadata_fetch", fake)
        result = get_beatmap_metadata_fetch(state)
        assert result is fake

    def test_get_beatmap_metadata_fetch_returns_none_when_missing(self) -> None:
        state = TaskiqState()
        result = get_beatmap_metadata_fetch(state)
        assert result is None

    def test_get_beatmap_file_fetch_returns_service(self) -> None:
        fake = _FakeJob()
        state = TaskiqState()
        object.__setattr__(state, "beatmap_file_fetch", fake)
        result = get_beatmap_file_fetch(state)
        assert result is fake

    def test_get_beatmap_file_fetch_returns_none_when_missing(self) -> None:
        state = TaskiqState()
        result = get_beatmap_file_fetch(state)
        assert result is None

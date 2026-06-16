"""Unit tests for the taskiq worker lifecycle."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest
import structlog
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

import osu_server.worker as worker_module
from osu_server.composition.providers.container import make_worker_container
from osu_server.composition.providers.test import make_in_memory_runtime_provider_set
from osu_server.config import AppConfig
from osu_server.jobs.chat_persistence import persist_private_message
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.commands.chat import (
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
)
from osu_server.services.commands.scores.performance import (
    ExecutePerformanceCalculationUseCase,
    ProcessPerformanceRecalculationBatchUseCase,
)
from osu_server.services.queries.chat import (
    ListPrivateMessagesQuery,
    ListPrivateMessagesQueryInput,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from pathlib import Path

    from dishka import AsyncContainer

    from osu_server.domain.beatmaps import BeatmapFetchTarget

    WorkerLifecycleHook = Callable[[TaskiqState], Awaitable[None]]


class FakeDishkaContainer:
    """AsyncContainer test double that records close calls."""

    close_calls: int

    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FailingWorkerContainer:
    """Worker container fake that fails while resolving the file fetch use-case."""

    close_calls: int

    def __init__(self) -> None:
        self.close_calls = 0

    async def get(self, dependency_type: type[object]) -> object:
        if dependency_type is FetchBeatmapFileUseCase:
            msg = "beatmap file fetch unavailable"
            raise RuntimeError(msg)
        return object()

    async def close(self) -> None:
        self.close_calls += 1


@dataclass(frozen=True, slots=True)
class RecordedBeatmapFetch:
    target_type: str
    target_key: str


class FakeBeatmapFetchUseCase:
    """Beatmap fetch use-case fake that records task adapter calls."""

    calls: list[BeatmapFetchTarget]

    def __init__(self) -> None:
        self.calls = []

    async def execute(self, target: BeatmapFetchTarget) -> None:
        self.calls.append(target)


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "valkey_url": "redis://localhost:6379/0",
            "environment": "test",
            "log_dir": str(tmp_path),
            "blob_storage_local_root": str(tmp_path / "blobs"),
        }
    )


def _install_in_memory_worker_container(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    config: AppConfig,
) -> None:
    def make_test_worker_container(app_config: AppConfig) -> AsyncContainer:
        return make_worker_container(
            app_config,
            overrides=(
                make_in_memory_runtime_provider_set(
                    blob_root=tmp_path / "blobs",
                ),
            ),
        )

    monkeypatch.setattr(worker_module, "_config", config)
    monkeypatch.setattr(
        worker_module,
        "make_worker_container",
        make_test_worker_container,
    )


def _make_task_context(private_message_use_case: object) -> Context:
    broker = InMemoryBroker()
    broker.state.persist_private_message_use_case = private_message_use_case
    message = TaskiqMessage(
        task_id="worker-test-id",
        task_name="persist_private_message",
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


def _state_dishka_container(state: TaskiqState) -> AsyncContainer | None:
    return cast("AsyncContainer | None", getattr(state, "dishka_container", None))


def _state_persist_channel_message_use_case(state: TaskiqState) -> object | None:
    return cast("object | None", getattr(state, "persist_channel_message_use_case", None))


def _state_persist_private_message_use_case(state: TaskiqState) -> object | None:
    return cast("object | None", getattr(state, "persist_private_message_use_case", None))


def _state_beatmap_metadata_fetch(state: TaskiqState) -> object | None:
    return cast("object | None", getattr(state, "beatmap_metadata_fetch", None))


def _state_beatmap_file_fetch(state: TaskiqState) -> object | None:
    return cast("object | None", getattr(state, "beatmap_file_fetch", None))


def _state_score_performance_calculation_executor(state: TaskiqState) -> object | None:
    return cast("object | None", getattr(state, "score_performance_calculation_executor", None))


def _state_performance_recalculation_batch_processor(state: TaskiqState) -> object | None:
    return cast("object | None", getattr(state, "performance_recalculation_batch_processor", None))


async def _run_startup(state: TaskiqState) -> None:
    hook = cast("WorkerLifecycleHook", worker_module.startup)
    await hook(state)


async def _run_shutdown(state: TaskiqState) -> None:
    hook = cast("WorkerLifecycleHook", worker_module.shutdown)
    await hook(state)


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    yield

    for handler in root.handlers:
        if hasattr(handler, "close"):
            handler.close()
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(logger_name).handlers:
            if hasattr(handler, "close"):
                handler.close()
    root.handlers = original_handlers
    root.level = original_level
    structlog.reset_defaults()


@pytest.mark.asyncio
async def test_worker_startup_configures_logging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = TaskiqState()
    config = _make_config(tmp_path)
    _install_in_memory_worker_container(monkeypatch, tmp_path=tmp_path, config=config)

    await _run_startup(state)
    await _run_shutdown(state)

    logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]
    logger.info("worker_test_event", password="my_secret_password")

    json_path = tmp_path / "latest.jsonl"
    content = json_path.read_text().strip()
    assert content != ""
    parsed = cast("dict[str, object]", json.loads(content.split("\n")[-1]))
    assert parsed["event"] == "worker_test_event"
    assert parsed["password"] == "***"


@pytest.mark.asyncio
async def test_worker_startup_sets_task_use_cases_from_dishka_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = TaskiqState()
    config = _make_config(tmp_path)
    _install_in_memory_worker_container(monkeypatch, tmp_path=tmp_path, config=config)

    await _run_startup(state)
    try:
        assert _state_dishka_container(state) is not None
        assert isinstance(
            _state_persist_channel_message_use_case(state),
            PersistChannelMessageUseCase,
        )
        assert isinstance(
            _state_persist_private_message_use_case(state),
            PersistPrivateMessageUseCase,
        )
        assert isinstance(_state_beatmap_metadata_fetch(state), FetchBeatmapMetadataUseCase)
        assert isinstance(_state_beatmap_file_fetch(state), FetchBeatmapFileUseCase)
        assert isinstance(
            _state_score_performance_calculation_executor(state),
            ExecutePerformanceCalculationUseCase,
        )
        assert isinstance(
            _state_performance_recalculation_batch_processor(state),
            ProcessPerformanceRecalculationBatchUseCase,
        )
    finally:
        await _run_shutdown(state)


@pytest.mark.asyncio
async def test_worker_startup_failure_closes_dishka_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = TaskiqState()
    config = _make_config(tmp_path)
    failing_container = FailingWorkerContainer()

    def make_failing_worker_container(_: AppConfig) -> FailingWorkerContainer:
        return failing_container

    monkeypatch.setattr(worker_module, "_config", config)
    monkeypatch.setattr(
        worker_module,
        "make_worker_container",
        make_failing_worker_container,
    )

    with pytest.raises(RuntimeError, match="beatmap file fetch unavailable"):
        await _run_startup(state)

    assert _state_dishka_container(state) is None
    assert _state_persist_channel_message_use_case(state) is None
    assert _state_persist_private_message_use_case(state) is None
    assert _state_beatmap_metadata_fetch(state) is None
    assert _state_beatmap_file_fetch(state) is None
    assert _state_score_performance_calculation_executor(state) is None
    assert _state_performance_recalculation_batch_processor(state) is None
    assert failing_container.close_calls == 1


@pytest.mark.asyncio
async def test_worker_runtime_chat_use_case_executes_persistence_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = TaskiqState()
    config = _make_config(tmp_path)
    _install_in_memory_worker_container(monkeypatch, tmp_path=tmp_path, config=config)

    await _run_startup(state)
    try:
        private_message_use_case = _state_persist_private_message_use_case(state)
        assert private_message_use_case is not None
        await persist_private_message(
            sender_id=1,
            target_id=2,
            sender_name="sender",
            target_name="target",
            content="secret",
            context=_make_task_context(private_message_use_case),
        )

        container = _state_dishka_container(state)
        assert container is not None
        query = await container.get(ListPrivateMessagesQuery)
        result = await query.execute(
            ListPrivateMessagesQueryInput(user_id=1, peer_user_id=2, limit=10)
        )

        assert [message.content for message in result.messages] == ["secret"]
    finally:
        await _run_shutdown(state)


@pytest.mark.asyncio
async def test_worker_shutdown_clears_runtime_state() -> None:
    state = TaskiqState()
    dishka_container = FakeDishkaContainer()
    state.dishka_container = dishka_container
    state.persist_channel_message_use_case = object()
    state.persist_private_message_use_case = object()
    state.beatmap_metadata_fetch = object()
    state.beatmap_file_fetch = object()
    state.score_performance_calculation_executor = object()
    state.performance_recalculation_batch_processor = object()

    await _run_shutdown(state)

    assert _state_dishka_container(state) is None
    assert _state_persist_channel_message_use_case(state) is None
    assert _state_persist_private_message_use_case(state) is None
    assert _state_beatmap_metadata_fetch(state) is None
    assert _state_beatmap_file_fetch(state) is None
    assert _state_score_performance_calculation_executor(state) is None
    assert _state_performance_recalculation_batch_processor(state) is None
    assert dishka_container.close_calls == 1

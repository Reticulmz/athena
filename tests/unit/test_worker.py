"""Unit tests for the taskiq worker logging configuration."""

from __future__ import annotations

import json
import logging
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from taskiq import Context, InMemoryBroker, TaskiqMessage, TaskiqState

from osu_server.config import AppConfig
from osu_server.jobs.beatmap_fetch import fetch_beatmap_file, fetch_beatmap_metadata
from osu_server.jobs.chat_persistence import persist_private_message
from osu_server.worker import shutdown, startup

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import TracebackType

    from dishka import AsyncContainer

    from osu_server.domain.beatmaps import BeatmapFetchTarget


class FakeEngine:
    """AsyncEngine test double that records dispose calls."""

    dispose_calls: int

    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        """Record engine disposal."""
        self.dispose_calls += 1


class FakeValkeyClient:
    """GlideClient test double that records close calls."""

    close_calls: int

    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        """Record client shutdown."""
        self.close_calls += 1


class FakeDishkaContainer:
    """AsyncContainer test double that records close calls."""

    close_calls: int

    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        """Record container close."""
        self.close_calls += 1


@dataclass(frozen=True, slots=True)
class RecordedPrivateMessage:
    sender_id: int
    target_user_id: int
    content: str


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    """Session fake for worker runtime persistence tests."""

    added: list[object]
    private_messages: list[RecordedPrivateMessage]
    commits: int
    rollbacks: int
    flushes: int
    closed: bool

    def __init__(self) -> None:
        self.added = []
        self.private_messages = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.closed = False

    @override
    async def __aenter__(self) -> FakeSession:
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc
        _ = traceback

    def add(self, instance: object) -> None:
        """Record the object added by the repository."""
        self.added.append(instance)
        if instance.__class__.__name__ == "PrivateMessageModel":
            self.private_messages.append(
                RecordedPrivateMessage(
                    sender_id=_int_attr(instance, "sender_id"),
                    target_user_id=_int_attr(instance, "target_user_id"),
                    content=_str_attr(instance, "content"),
                )
            )

    async def flush(self) -> None:
        """Record flush calls."""
        self.flushes += 1

    async def commit(self) -> None:
        """Record commit calls."""
        self.commits += 1

    async def rollback(self) -> None:
        """Record rollback calls."""
        self.rollbacks += 1

    async def close(self) -> None:
        """Record session close."""
        self.closed = True


class FakeSessionFactory:
    """Callable fake compatible with worker repository construction."""

    _session: FakeSession

    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> FakeSession:
        return self._session


class FakeBeatmapFetchUseCase:
    """Beatmap fetch use-case fake that records task adapter calls."""

    calls: list[BeatmapFetchTarget]

    def __init__(self) -> None:
        self.calls = []

    async def execute(self, target: BeatmapFetchTarget) -> None:
        self.calls.append(target)


def _make_config(tmp_path: Path) -> AppConfig:
    """Create worker config for unit tests."""
    return AppConfig.model_validate(
        {
            "database_url": "postgresql://test:test@localhost:5432/test",
            "valkey_url": "redis://localhost:6379/0",
            "environment": "test",
            "log_dir": str(tmp_path),
        }
    )


def _int_attr(instance: object, name: str) -> int:
    value = cast("object", getattr(instance, name))
    if not isinstance(value, int):
        msg = f"expected {name} to be int"
        raise TypeError(msg)
    return value


def _str_attr(instance: object, name: str) -> str:
    value = cast("object", getattr(instance, name))
    if not isinstance(value, str):
        msg = f"expected {name} to be str"
        raise TypeError(msg)
    return value


def _make_task_context(private_message_use_case: object) -> Context:
    """Create a taskiq context carrying worker runtime state."""
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


def _make_beatmap_task_context(
    *,
    task_name: str,
    metadata_fetch: object | None = None,
    file_fetch: object | None = None,
) -> Context:
    """Create a taskiq context carrying worker beatmap runtime state."""
    broker = InMemoryBroker()
    if metadata_fetch is not None:
        broker.state.beatmap_metadata_fetch = metadata_fetch
    if file_fetch is not None:
        broker.state.beatmap_file_fetch = file_fetch
    message = TaskiqMessage(
        task_id="worker-beatmap-test-id",
        task_name=task_name,
        labels={},
        args=[],
        kwargs={},
    )
    return Context(message, broker)


def _state_engine(state: TaskiqState) -> FakeEngine | None:
    """Return typed worker engine state for assertions."""
    return cast("FakeEngine | None", getattr(state, "engine", None))


def _state_session_factory(state: TaskiqState) -> FakeSessionFactory | None:
    """Return typed worker session factory state for assertions."""
    return cast("FakeSessionFactory | None", getattr(state, "session_factory", None))


def _state_valkey(state: TaskiqState) -> FakeValkeyClient | None:
    """Return typed worker Valkey state for assertions."""
    return cast("FakeValkeyClient | None", getattr(state, "valkey", None))


def _state_dishka_container(state: TaskiqState) -> AsyncContainer | None:
    """Return typed worker Dishka container state for assertions."""
    return cast("AsyncContainer | None", getattr(state, "dishka_container", None))


def _state_persist_channel_message_use_case(state: TaskiqState) -> object | None:
    """Return typed worker channel persistence use-case state for assertions."""
    return cast("object | None", getattr(state, "persist_channel_message_use_case", None))


def _state_persist_private_message_use_case(state: TaskiqState) -> object | None:
    """Return typed worker private persistence use-case state for assertions."""
    return cast("object | None", getattr(state, "persist_private_message_use_case", None))


def _state_beatmap_metadata_fetch(state: TaskiqState) -> object | None:
    """Return typed worker beatmap metadata fetch state for assertions."""
    return cast("object | None", getattr(state, "beatmap_metadata_fetch", None))


def _state_beatmap_file_fetch(state: TaskiqState) -> object | None:
    """Return typed worker beatmap file fetch state for assertions."""
    return cast("object | None", getattr(state, "beatmap_file_fetch", None))


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Reset stdlib root logger and structlog config between tests."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    yield

    # Close handlers added by setup_logging
    # (including uvicorn handlers via _override_uvicorn_handlers)
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
async def test_worker_startup_configures_logging(tmp_path: Path) -> None:
    """ワーカー起動時に setup_logging が実行され、カスタムプロセッサ (マスク処理) が有効になる."""
    state = TaskiqState()

    async def create_valkey_client(_: str) -> FakeValkeyClient:
        return FakeValkeyClient()

    # DB接続処理などをモック化して、logging の動作確認に専念する
    with (
        patch("osu_server.worker.create_engine"),
        patch("osu_server.worker.create_session_factory"),
        patch("osu_server.worker.create_valkey_client", new=create_valkey_client, create=True),
        patch(
            "osu_server.worker.create_worker_chat_persistence_use_cases",
            return_value=(object(), object()),
            create=True,
        ),
        patch(
            "osu_server.worker.create_worker_beatmap_metadata_fetch",
            return_value=object(),
            create=True,
        ),
        patch(
            "osu_server.worker.create_worker_beatmap_file_fetch",
            new=AsyncMock(return_value=object()),
            create=True,
        ),
        patch("osu_server.worker._config") as mock_config,
    ):
        mock_config.log_dir = str(tmp_path)
        mock_config.log_max_files = 30
        mock_config.log_level = "INFO"
        mock_config.valkey_url = "redis://localhost:6379/0"

        _ = await startup(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]
    logger.info("worker_test_event", password="my_secret_password")

    # latest.jsonl からログを読み込んで検証する
    json_path = tmp_path / "latest.jsonl"
    content = json_path.read_text().strip()
    assert content != ""
    parsed: dict[str, object] = json.loads(content.split("\n")[-1])  # pyright: ignore[reportAny]
    assert parsed["event"] == "worker_test_event"
    # mask_sensitive_fields が適用されていることの確認
    assert parsed["password"] == "***"


@pytest.mark.asyncio
async def test_worker_startup_sets_chat_persistence_runtime_state(tmp_path: Path) -> None:
    """Worker startup exposes chat persistence use-cases through taskiq state."""
    state = TaskiqState()
    engine = FakeEngine()
    session = FakeSession()
    session_factory = FakeSessionFactory(session)
    valkey = FakeValkeyClient()

    async def create_valkey_client(_: str) -> FakeValkeyClient:
        return valkey

    with (
        patch("osu_server.worker.create_engine", return_value=engine),
        patch("osu_server.worker.create_session_factory", return_value=session_factory),
        patch("osu_server.worker.create_valkey_client", new=create_valkey_client, create=True),
        patch("osu_server.worker._config", _make_config(tmp_path)),
    ):
        _ = await startup(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    assert _state_engine(state) is engine
    assert _state_session_factory(state) is session_factory
    assert _state_valkey(state) is valkey
    assert _state_dishka_container(state) is not None
    assert _state_persist_channel_message_use_case(state) is not None
    assert _state_persist_private_message_use_case(state) is not None


@pytest.mark.asyncio
async def test_worker_startup_failure_closes_runtime_dependencies(tmp_path: Path) -> None:
    """Worker startup failure closes partially constructed runtime dependencies."""
    state = TaskiqState()
    engine = FakeEngine()
    session = FakeSession()
    session_factory = FakeSessionFactory(session)
    valkey = FakeValkeyClient()

    async def create_valkey_client(_: str) -> FakeValkeyClient:
        return valkey

    async def create_worker_beatmap_file_fetch(
        *,
        session_factory: FakeSessionFactory,
        config: AppConfig,
    ) -> object:
        _ = session_factory
        _ = config
        msg = "beatmap file fetch unavailable"
        raise RuntimeError(msg)

    with (
        patch("osu_server.worker.create_engine", return_value=engine),
        patch("osu_server.worker.create_session_factory", return_value=session_factory),
        patch("osu_server.worker.create_valkey_client", new=create_valkey_client, create=True),
        patch("osu_server.worker._config", _make_config(tmp_path)),
        patch(
            "osu_server.worker.create_worker_beatmap_file_fetch",
            new=create_worker_beatmap_file_fetch,
            create=True,
        ),
        pytest.raises(RuntimeError, match="beatmap file fetch unavailable"),
    ):
        _ = await startup(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    assert _state_engine(state) is None
    assert _state_session_factory(state) is None
    assert _state_valkey(state) is None
    assert _state_dishka_container(state) is None
    assert _state_persist_channel_message_use_case(state) is None
    assert _state_persist_private_message_use_case(state) is None
    assert _state_beatmap_metadata_fetch(state) is None
    assert _state_beatmap_file_fetch(state) is None
    assert engine.dispose_calls == 1
    assert valkey.close_calls == 1


@pytest.mark.asyncio
async def test_worker_runtime_chat_use_case_executes_persistence_task(tmp_path: Path) -> None:
    """Persistence task resolves the startup use-case from worker runtime state."""
    state = TaskiqState()
    engine = FakeEngine()
    session = FakeSession()
    session_factory = FakeSessionFactory(session)
    valkey = FakeValkeyClient()

    async def create_valkey_client(_: str) -> FakeValkeyClient:
        return valkey

    with (
        patch("osu_server.worker.create_engine", return_value=engine),
        patch("osu_server.worker.create_session_factory", return_value=session_factory),
        patch("osu_server.worker.create_valkey_client", new=create_valkey_client, create=True),
        patch("osu_server.worker._config", _make_config(tmp_path)),
    ):
        _ = await startup(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    private_message_use_case = _state_persist_private_message_use_case(state)
    assert private_message_use_case is not None
    context = _make_task_context(private_message_use_case)
    await persist_private_message(
        sender_id=1,
        target_id=2,
        sender_name="sender",
        target_name="target",
        content="secret",
        context=context,
    )

    assert session.commits == 1
    assert session.flushes == 1
    assert session.closed is True
    assert session.private_messages == [
        RecordedPrivateMessage(
            sender_id=1,
            target_user_id=2,
            content="secret",
        )
    ]


@pytest.mark.asyncio
async def test_worker_shutdown_clears_chat_runtime_state() -> None:
    """Worker shutdown clears and closes runtime state owned by startup."""
    state = TaskiqState()
    engine = FakeEngine()
    valkey = FakeValkeyClient()
    dishka_container = FakeDishkaContainer()
    channel_use_case = object()
    private_use_case = object()
    session_factory = object()

    state.engine = engine
    state.valkey = valkey
    state.dishka_container = dishka_container
    state.persist_channel_message_use_case = channel_use_case
    state.persist_private_message_use_case = private_use_case
    state.session_factory = session_factory

    _ = await shutdown(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    assert _state_engine(state) is None
    assert _state_session_factory(state) is None
    assert _state_persist_channel_message_use_case(state) is None
    assert _state_persist_private_message_use_case(state) is None
    assert _state_valkey(state) is None
    assert _state_dishka_container(state) is None
    assert engine.dispose_calls == 1
    assert valkey.close_calls == 1
    assert dishka_container.close_calls == 1


# ---------------------------------------------------------------------------
# Beatmap fetch job runtime state tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_startup_sets_beatmap_fetch_runtime_state(tmp_path: Path) -> None:
    """Worker startup exposes beatmap fetch jobs through taskiq state."""
    state = TaskiqState()
    engine = FakeEngine()
    session = FakeSession()
    session_factory = FakeSessionFactory(session)
    valkey = FakeValkeyClient()
    fake_metadata_job = object()
    fake_file_job = object()

    async def create_valkey_client(_: str) -> FakeValkeyClient:
        return valkey

    with (
        patch("osu_server.worker.create_engine", return_value=engine),
        patch("osu_server.worker.create_session_factory", return_value=session_factory),
        patch("osu_server.worker.create_valkey_client", new=create_valkey_client, create=True),
        patch("osu_server.worker._config", _make_config(tmp_path)),
        patch(
            "osu_server.worker.create_worker_beatmap_metadata_fetch",
            return_value=fake_metadata_job,
            create=True,
        ),
        patch(
            "osu_server.worker.create_worker_beatmap_file_fetch",
            return_value=fake_file_job,
            create=True,
        ),
    ):
        _ = await startup(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    assert _state_beatmap_metadata_fetch(state) is fake_metadata_job
    assert _state_beatmap_file_fetch(state) is fake_file_job


@pytest.mark.asyncio
async def test_worker_runtime_beatmap_tasks_use_startup_use_cases(tmp_path: Path) -> None:
    """Beatmap tasks resolve the startup use-cases through worker runtime state."""
    state = TaskiqState()
    engine = FakeEngine()
    session = FakeSession()
    session_factory = FakeSessionFactory(session)
    valkey = FakeValkeyClient()
    metadata_use_case = FakeBeatmapFetchUseCase()
    file_use_case = FakeBeatmapFetchUseCase()

    async def create_valkey_client(_: str) -> FakeValkeyClient:
        return valkey

    with (
        patch("osu_server.worker.create_engine", return_value=engine),
        patch("osu_server.worker.create_session_factory", return_value=session_factory),
        patch("osu_server.worker.create_valkey_client", new=create_valkey_client, create=True),
        patch("osu_server.worker._config", _make_config(tmp_path)),
        patch(
            "osu_server.worker.create_worker_beatmap_metadata_fetch",
            return_value=metadata_use_case,
            create=True,
        ),
        patch(
            "osu_server.worker.create_worker_beatmap_file_fetch",
            return_value=file_use_case,
            create=True,
        ),
    ):
        _ = await startup(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    metadata_fetch = _state_beatmap_metadata_fetch(state)
    file_fetch = _state_beatmap_file_fetch(state)
    assert metadata_fetch is metadata_use_case
    assert file_fetch is file_use_case

    await fetch_beatmap_metadata(
        target_type="metadata:beatmap",
        target_key="2000",
        context=_make_beatmap_task_context(
            task_name="fetch_beatmap_metadata",
            metadata_fetch=metadata_fetch,
        ),
    )
    await fetch_beatmap_file(
        target_type="file:beatmap",
        target_key="2000",
        context=_make_beatmap_task_context(
            task_name="fetch_beatmap_file",
            file_fetch=file_fetch,
        ),
    )

    assert [(target.target_type, target.target_key) for target in metadata_use_case.calls] == [
        ("metadata:beatmap", "2000")
    ]
    assert [(target.target_type, target.target_key) for target in file_use_case.calls] == [
        ("file:beatmap", "2000")
    ]


@pytest.mark.asyncio
async def test_worker_shutdown_clears_beatmap_fetch_runtime_state() -> None:
    """Worker shutdown clears beatmap fetch runtime state owned by startup."""
    state = TaskiqState()
    engine = FakeEngine()
    valkey = FakeValkeyClient()
    metadata_job = object()
    file_job = object()

    state.engine = engine
    state.valkey = valkey
    state.beatmap_metadata_fetch = metadata_job
    state.beatmap_file_fetch = file_job

    _ = await shutdown(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    assert _state_beatmap_metadata_fetch(state) is None
    assert _state_beatmap_file_fetch(state) is None
    assert engine.dispose_calls == 1
    assert valkey.close_calls == 1

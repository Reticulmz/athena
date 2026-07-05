"""Global test fixtures for structlog state management and DI container cleanup."""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Generator, Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from pathlib import Path
from typing import Protocol, cast, final

import pytest
import structlog
from glide import GlideClient
from taskiq_redis import ListQueueBroker

import osu_server.infrastructure.cache.valkey_client as valkey_module
from osu_server.shared.query_diagnostics import (
    QueryDiagnosticSummary,
    query_diagnostic_scope,
)

# ---------------------------------------------------------------------------
# Runtime resource tracking -- ensures sockets are closed after tests
# ---------------------------------------------------------------------------

_TEST_ENV_FILE = Path(".env.test")
_TEST_SERVICE_ENV_VARS = frozenset({"DATABASE_URL", "VALKEY_URL"})

type _ValkeyClientFactory = Callable[[str], Awaitable[GlideClient]]
type _BrokerInitializer = Callable[..., None]


class _AsyncCloseable(Protocol):
    async def close(self) -> None: ...


class _AsyncShutdownBroker(Protocol):
    async def shutdown(self) -> None: ...


class QueryBudget(Protocol):
    """SQL query budget fixture の callable contract.

    __call__ Args:
        max_queries: Scope 内で許可する最大 SQL query 数.
        name: Failure message に出す redacted scope 名.
        duplicate_threshold: Duplicate として扱う同一 SQL template の最小回数.

    __call__ Returns:
        SQL query count を検査する context manager.

    __call__ Raises:
        ValueError: max_queries が 0 未満の場合.
        AssertionError: Scope 内の SQL query count が max_queries を超えた場合.
    """

    def __call__(
        self,
        *,
        max_queries: int,
        name: str,
        duplicate_threshold: int = 2,
    ) -> AbstractContextManager[None]: ...


@final
class RuntimeResourceTracker:
    """Owns test-suite runtime patches and resource cleanup."""

    _glide_clients: list[weakref.ReferenceType[object]]
    _brokers: list[weakref.ReferenceType[object]]
    _original_create_valkey_client: _ValkeyClientFactory | None
    _original_list_queue_broker_init: _BrokerInitializer | None

    def __init__(self) -> None:
        self._glide_clients = []
        self._brokers = []
        self._original_create_valkey_client = None
        self._original_list_queue_broker_init = None

    def install_patches(self) -> None:
        """Patch runtime constructors early so leaked resources are tracked."""
        self._original_create_valkey_client = valkey_module.create_valkey_client
        self._original_list_queue_broker_init = ListQueueBroker.__init__

        async def tracked_create_valkey_client(valkey_url: str) -> GlideClient:
            original = self._original_create_valkey_client
            if original is None:
                msg = "Valkey client factory patch is not installed"
                raise RuntimeError(msg)
            client = await original(valkey_url)
            self._track_glide_client(client)
            return client

        tracker = self

        def tracked_broker_init(
            self: ListQueueBroker,
            *args: object,
            **kwargs: object,
        ) -> None:
            original = tracker._original_list_queue_broker_init
            if original is None:
                msg = "ListQueueBroker initializer patch is not installed"
                raise RuntimeError(msg)
            original(self, *args, **kwargs)
            tracker._brokers.append(weakref.ref(self))

        valkey_module.create_valkey_client = tracked_create_valkey_client
        ListQueueBroker.__init__ = tracked_broker_init

    def restore_patches(self) -> None:
        """Restore runtime constructors patched for test cleanup."""
        if self._original_create_valkey_client is not None:
            valkey_module.create_valkey_client = self._original_create_valkey_client
            self._original_create_valkey_client = None
        if self._original_list_queue_broker_init is not None:
            ListQueueBroker.__init__ = self._original_list_queue_broker_init
            self._original_list_queue_broker_init = None

    async def close_after_test(self) -> None:
        """Close tracked clients and brokers created by a test."""
        for ref in self._glide_clients:
            client = ref()
            if client is not None:
                closeable = _as_async_closeable(client)
                if closeable is not None:
                    with suppress(Exception):
                        await closeable.close()
        self._glide_clients.clear()

        alive_brokers: list[weakref.ReferenceType[object]] = []
        for ref in self._brokers:
            broker = ref()
            if broker is not None:
                alive_brokers.append(ref)
                shutdown_broker = _as_async_shutdown_broker(broker)
                if shutdown_broker is not None:
                    with suppress(Exception):
                        await shutdown_broker.shutdown()
        self._brokers = alive_brokers
        if self._brokers:
            await asyncio.sleep(0)
        # _brokers is intentionally retained: module-level singleton brokers
        # can reconnect between tests and need closing after later tests too.

    def _track_glide_client(self, client: object) -> None:
        self._glide_clients.append(weakref.ref(client))


def _as_async_closeable(value: object) -> _AsyncCloseable | None:
    if callable(getattr(value, "close", None)):
        return cast("_AsyncCloseable", value)
    return None


def _as_async_shutdown_broker(value: object) -> _AsyncShutdownBroker | None:
    if callable(getattr(value, "shutdown", None)):
        return cast("_AsyncShutdownBroker", value)
    return None


_runtime_resources = RuntimeResourceTracker()


def _load_test_service_env_defaults() -> None:
    """Expose .env.test service URLs to tests that read os.environ directly."""
    if not _TEST_ENV_FILE.exists():
        return

    for raw_line in _TEST_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in _TEST_SERVICE_ENV_VARS:
            continue
        value = raw_value.strip().strip("\"'")
        _ = os.environ.setdefault(key, value)


@pytest.fixture(autouse=True)
async def close_runtime_resources() -> AsyncIterator[None]:
    """Close all GlideClient and broker instances created during a test."""
    yield
    await _runtime_resources.close_after_test()


def pytest_configure(config: pytest.Config) -> None:
    """Patch create_valkey_client and ListQueueBroker early, before test imports."""
    _ = config
    _ = os.environ.setdefault("ENVIRONMENT", "test")
    _load_test_service_env_defaults()
    _runtime_resources.install_patches()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore original runtime constructors."""
    _ = config
    _runtime_resources.restore_patches()


# ---------------------------------------------------------------------------
# structlog reset
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_structlog() -> Iterator[None]:
    """Reset structlog configuration before each test.

    Ensures capture_logs() works correctly regardless of test ordering,
    by preventing logger caching across tests.
    """
    structlog.configure(cache_logger_on_first_use=False)

    yield

    structlog.configure(cache_logger_on_first_use=False)
    root = logging.getLogger()
    # Close all handlers (root + uvicorn loggers set up by setup_logging)
    all_handlers: list[logging.Handler] = list(root.handlers)
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        all_handlers.extend(logging.getLogger(logger_name).handlers)
    for handler in all_handlers:
        handler.close()
    root.handlers.clear()
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).handlers.clear()
    root.setLevel(logging.WARNING)


@pytest.fixture
def query_budget() -> QueryBudget:
    """SQL query count を opt-in で hard fail する fixture.

    Args:
        なし. fixture 自体は factory を返す.

    Returns:
        max_queries, name, duplicate_threshold を受け取り context manager を返す
        callable.

    Raises:
        ValueError: max_queries が 0 未満の場合.
        AssertionError: Scope 内の SQL query count が max_queries を超えた場合.

    Constraints:
        Scope 内で発生した例外は budget check より優先して伝播する.
    """

    @contextmanager
    def budget(
        *,
        max_queries: int,
        name: str,
        duplicate_threshold: int = 2,
    ) -> Generator[None]:
        if max_queries < 0:
            msg = "max_queries must be greater than or equal to 0"
            raise ValueError(msg)
        with query_diagnostic_scope(
            scope_kind="test",
            scope_name=name,
            duplicate_threshold=duplicate_threshold,
        ) as collector:
            yield
        summary = collector.summary()
        if summary.total_queries > max_queries:
            raise AssertionError(_format_query_budget_failure(summary, max_queries))

    return budget


def _format_query_budget_failure(
    summary: QueryDiagnosticSummary,
    max_queries: int,
) -> str:
    duplicate_lines = [
        " ".join(
            (
                f"  - count={duplicate.count}",
                f"fingerprint={duplicate.fingerprint}",
                f"sql_prefix={duplicate.sql_prefix!r}",
            )
        )
        for duplicate in summary.duplicate_queries
    ]
    duplicates = "\n".join(duplicate_lines) if duplicate_lines else "  - none"
    return "\n".join(
        (
            "SQL query budget exceeded",
            f"scope={summary.scope_kind}:{summary.scope_name}",
            f"actual={summary.total_queries}",
            f"allowed={max_queries}",
            f"duplicate_templates_total={summary.duplicate_templates_total}",
            f"duplicates_truncated={summary.duplicates_truncated}",
            "duplicates:",
            duplicates,
        )
    )

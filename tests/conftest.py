"""Global test fixtures for structlog state management and DI container cleanup."""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Protocol, cast, final

import pytest
import structlog
from glide import GlideClient
from taskiq_redis import ListQueueBroker

import osu_server.infrastructure.cache.valkey_client as valkey_module

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

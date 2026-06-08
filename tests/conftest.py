"""Global test fixtures for structlog state management and DI container cleanup."""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from contextlib import suppress
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

import pytest

# ---------------------------------------------------------------------------
# GlideClient tracking — ensures GlideClient sockets are closed after tests
# ---------------------------------------------------------------------------

_glide_clients: list[weakref.ReferenceType[object]] = []


def _track_glide_client(client: object) -> None:
    _glide_clients.append(weakref.ref(client))


@pytest.fixture(autouse=True)
async def _close_glide_clients() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Close all GlideClient and broker instances created during a test."""
    yield
    for ref in _glide_clients:
        client = ref()
        if client is not None:
            with suppress(Exception):
                await client.close()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
    _glide_clients.clear()
    for ref in _brokers:
        broker = ref()
        if broker is not None:
            with suppress(Exception):
                await broker.shutdown()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
    if _brokers:
        await asyncio.sleep(0)
    # NOTE: _brokers is NOT cleared — module-level singleton brokers (e.g. worker.py)
    # persist across tests and may re-establish connections that need closing.


# -- Monkey-patch create_valkey_client to track GlideClient instances ---------

_original_create_valkey_client = None
_original_list_queue_broker_init = None
_brokers: list[weakref.ReferenceType[object]] = []


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
    """Patch create_valkey_client and ListQueueBroker early, before test imports."""
    _ = os.environ.setdefault("ENVIRONMENT", "test")

    # -- Patch create_valkey_client
    import osu_server.infrastructure.cache.valkey_client as _valkey_mod  # noqa: PLC0415

    global _original_create_valkey_client  # noqa: PLW0603
    _original_create_valkey_client = _valkey_mod.create_valkey_client
    assert _original_create_valkey_client is not None

    async def _tracked_create(valkey_url: str) -> object:
        client = await _original_create_valkey_client(valkey_url)  # pyright: ignore[reportOptionalCall]
        _track_glide_client(client)
        return client

    _valkey_mod.create_valkey_client = _tracked_create  # type: ignore[assignment]

    # -- Patch ListQueueBroker.__init__ to track broker instances
    from taskiq_redis import ListQueueBroker  # noqa: PLC0415

    global _original_list_queue_broker_init  # noqa: PLW0603
    _original_list_queue_broker_init = ListQueueBroker.__init__

    def _tracked_broker_init(self: object, *args: object, **kwargs: object) -> None:
        _original_list_queue_broker_init(self, *args, **kwargs)  # pyright: ignore[reportArgumentType, reportOptionalCall]
        _brokers.append(weakref.ref(self))

    ListQueueBroker.__init__ = _tracked_broker_init  # type: ignore[reportAttributeAccessIssue]


def pytest_unconfigure(config: pytest.Config) -> None:  # noqa: ARG001  # pyright: ignore[reportUnusedParameter]
    """Restore original functions."""
    from taskiq_redis import ListQueueBroker  # noqa: PLC0415

    import osu_server.infrastructure.cache.valkey_client as _valkey_mod  # noqa: PLC0415

    global _original_create_valkey_client, _original_list_queue_broker_init  # noqa: PLW0603
    if _original_create_valkey_client is not None:
        _valkey_mod.create_valkey_client = _original_create_valkey_client  # type: ignore[assignment]
        _original_create_valkey_client = None
    if _original_list_queue_broker_init is not None:
        ListQueueBroker.__init__ = _original_list_queue_broker_init  # type: ignore[assignment]
        _original_list_queue_broker_init = None


# ---------------------------------------------------------------------------
# structlog reset
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
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
        if hasattr(handler, "close"):
            handler.close()
    root.handlers.clear()
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).handlers.clear()
    root.setLevel(logging.WARNING)

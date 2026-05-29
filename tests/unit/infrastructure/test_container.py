"""Tests for DI Container (TDD — RED phase first)."""

from __future__ import annotations

from typing import Protocol

import pytest

from osu_server.infrastructure.di.container import Container


class Greeter(Protocol):
    def greet(self) -> str: ...


class EnglishGreeter:
    def greet(self) -> str:
        return "hello"


class JapaneseGreeter:
    def greet(self) -> str:
        return "konnichiwa"


_ASYNC_SERVICE_VALUE = 42


class AsyncService:
    """Service created via async factory."""

    value: int

    def __init__(self, value: int) -> None:
        self.value = value


@pytest.fixture
def container() -> Container:
    return Container()


async def test_register_and_resolve(container: Container) -> None:
    """register a factory, resolve returns a new instance each call."""
    container.register(Greeter, EnglishGreeter)

    result = await container.resolve(Greeter)

    assert isinstance(result, EnglishGreeter)
    assert result.greet() == "hello"

    # Each resolve should return a NEW instance (transient)
    result2 = await container.resolve(Greeter)
    assert result is not result2


async def test_register_singleton_same_instance(container: Container) -> None:
    """register_singleton: two resolves return the exact same object."""
    container.register_singleton(Greeter, EnglishGreeter)

    first = await container.resolve(Greeter)
    second = await container.resolve(Greeter)

    assert first is second


async def test_resolve_unregistered_raises_key_error(container: Container) -> None:
    """resolve for an unknown type raises KeyError."""
    with pytest.raises(KeyError):
        _ = await container.resolve(Greeter)


async def test_initialize_creates_singletons(container: Container) -> None:
    """After initialize(), singletons are eagerly pre-created."""
    call_count = 0

    def factory() -> EnglishGreeter:
        nonlocal call_count
        call_count += 1
        return EnglishGreeter()

    container.register_singleton(Greeter, factory)

    # Factory not yet called
    assert call_count == 0

    await container.initialize()

    # Factory called exactly once during initialize
    assert call_count == 1

    # Subsequent resolve reuses the same instance (no extra call)
    result = await container.resolve(Greeter)
    assert call_count == 1
    assert isinstance(result, EnglishGreeter)


async def test_shutdown_calls_hooks(container: Container) -> None:
    """shutdown invokes registered shutdown hooks."""
    closed = False

    async def cleanup() -> None:
        nonlocal closed
        closed = True

    container.register_shutdown_hook(cleanup)

    await container.shutdown()

    assert closed is True


async def test_async_factory(container: Container) -> None:
    """Factory that is an async callable works correctly."""

    async def make_service() -> AsyncService:
        return AsyncService(value=_ASYNC_SERVICE_VALUE)

    container.register(AsyncService, make_service)

    result = await container.resolve(AsyncService)

    assert isinstance(result, AsyncService)
    assert result.value == _ASYNC_SERVICE_VALUE


async def test_register_overwrites(container: Container) -> None:
    """Registering the same type twice overwrites the first registration."""
    container.register(Greeter, EnglishGreeter)
    container.register(Greeter, JapaneseGreeter)

    result = await container.resolve(Greeter)

    assert isinstance(result, JapaneseGreeter)
    assert result.greet() == "konnichiwa"

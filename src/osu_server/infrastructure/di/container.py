"""Lightweight DI container with singleton support and lifecycle management."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import TypeVar, final

type Factory[T] = Callable[..., T | Awaitable[T]]
type ShutdownHook = Callable[[], Awaitable[None]]

T = TypeVar("T")


@final
class _Registration[T]:
    """Internal registration record."""

    __slots__ = ("factory", "instance", "singleton")

    def __init__(self, factory: Factory[T], *, singleton: bool) -> None:
        self.factory = factory
        self.singleton = singleton
        self.instance: T | None = None

    async def resolve(self) -> T:
        if self.singleton and self.instance is not None:
            return self.instance

        result = self.factory()
        if inspect.isawaitable(result):
            instance: T = await result
        else:
            instance = result

        if self.singleton:
            self.instance = instance

        return instance


class Container:
    """Simple DI container supporting transient and singleton registrations."""

    def __init__(self) -> None:
        self._registrations: dict[type[object], _Registration[object]] = {}
        self._shutdown_hooks: list[ShutdownHook] = []

    def register(
        self,
        interface: type[T],
        factory: Factory[T],
    ) -> None:
        """Register a transient factory -- creates a new instance every resolve."""
        self._registrations[interface] = _Registration(factory, singleton=False)

    def register_singleton(
        self,
        interface: type[T],
        factory: Factory[T],
    ) -> None:
        """Register a singleton factory -- first resolve creates, subsequent reuse."""
        self._registrations[interface] = _Registration(factory, singleton=True)

    async def resolve(self, interface: type[T]) -> T:
        """Resolve an instance. Raises KeyError if not registered."""
        try:
            registration = self._registrations[interface]
        except KeyError:
            raise KeyError(f"{interface!r} is not registered in the container") from None
        return await registration.resolve()  # pyright: ignore[reportReturnType]

    async def initialize(self) -> None:
        """Eagerly create all singletons -- validates everything is resolvable at startup."""
        coros = [reg.resolve() for reg in self._registrations.values() if reg.singleton]
        _ = await asyncio.gather(*coros)

    def register_shutdown_hook(self, hook: ShutdownHook) -> None:
        """Register an async callable to be invoked on shutdown."""
        self._shutdown_hooks.append(hook)

    async def shutdown(self) -> None:
        """Invoke all registered shutdown hooks."""
        for hook in self._shutdown_hooks:
            await hook()

"""Lightweight DI container with singleton support and lifecycle management."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import TypeVar, final

import structlog

type Factory[T] = Callable[..., T | Awaitable[T]]
type ShutdownHook = Callable[[], Awaitable[None]]

T = TypeVar("T")
logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@final
class _Registration[T]:
    """Internal registration record."""

    __slots__ = ("_lock", "factory", "instance", "singleton")

    def __init__(self, factory: Factory[T], *, singleton: bool) -> None:
        self.factory = factory
        self.singleton = singleton
        self.instance: T | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def resolve(self) -> T:
        # Fast path: already resolved singleton
        if self.singleton and self.instance is not None:
            return self.instance

        if not self.singleton:
            return await self._create()

        # Slow path: acquire lock, double-check, then create
        async with self._lock:
            if self.instance is not None:
                return self.instance
            instance = await self._create()
            self.instance = instance
            return instance

    async def _create(self) -> T:
        result = self.factory()
        if inspect.isawaitable(result):
            return await result
        return result  # type: ignore[return-value]


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
        """Invoke all registered shutdown hooks, ensuring all run even on failure."""
        for hook in self._shutdown_hooks:
            try:
                await hook()
            except Exception:
                logger.exception("shutdown_hook_failed", hook=repr(hook))

"""In-memory local event fanout."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)
TEvent = TypeVar("TEvent", bound=object)


class InMemoryLocalEventBus:
    """Local-only in-memory event fanout.

    Handlers are stored by concrete event type and invoked sequentially in
    registration order. Handler exceptions are caught and logged so one
    failing local handler does not block others.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[object], list[Callable[[object], Awaitable[None]]]] = (
            defaultdict(list)
        )

    async def fire(self, event: object) -> None:
        """Notify all local handlers registered for the event type."""
        for handler in self._handlers.get(type(event), []):
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "LocalEventBus handler %s failed for %s",
                    getattr(handler, "__name__", repr(handler)),
                    type(event).__name__,
                )

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], Awaitable[None]],
    ) -> None:
        """Register a local handler for a concrete event type."""
        self._handlers[event_type].append(cast("Callable[[object], Awaitable[None]]", handler))

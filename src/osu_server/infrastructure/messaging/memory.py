"""InMemoryEventBus — lightweight in-process event bus."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class InMemoryEventBus:
    """In-memory implementation of the EventBus Protocol.

    Handlers are stored in a ``dict[type, list[handler]]`` and invoked
    sequentially in registration order.  Handler exceptions are caught
    and logged so that one failing handler does not block others.
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[..., Awaitable[None]]]] = defaultdict(list)

    async def fire(self, event: object) -> None:
        """Publish an event to all registered handlers for its type."""
        for handler in self._handlers.get(type(event), []):
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    "EventBus handler %s failed for %s",
                    handler.__name__,
                    type(event).__name__,
                )

    def subscribe(self, event_type: type, handler: Callable[..., Awaitable[None]]) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type].append(handler)

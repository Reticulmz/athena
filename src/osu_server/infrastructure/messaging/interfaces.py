"""EventBus Protocol — abstract interface for event-driven messaging."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@runtime_checkable
class EventBus(Protocol):
    """Protocol for publishing and subscribing to domain events.

    Implementations must support fire (publish) and subscribe.
    """

    async def fire(self, event: object) -> None:
        """Publish an event to all registered handlers for its type.

        Handlers are called sequentially in registration order.
        Handler exceptions are caught and logged (fire-and-forget).
        """
        ...

    def subscribe(self, event_type: type, handler: Callable[..., Awaitable[None]]) -> None:
        """Register a handler for a specific event type.

        Multiple handlers can be registered for the same event type.
        Call order follows registration order.
        """
        ...

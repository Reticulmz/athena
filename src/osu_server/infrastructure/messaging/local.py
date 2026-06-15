"""Local-only event fanout contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

TEvent = TypeVar("TEvent", bound=object)


@runtime_checkable
class LocalEventBus(Protocol):
    """In-process event fanout contract.

    Implementations do not provide cross-replica, worker, durability, or replay
    guarantees. Use this only for same-process non-critical fanout.
    """

    async def fire(self, event: object) -> None:
        """Notify all local handlers subscribed for the event's concrete type."""
        ...

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], Awaitable[None]],
    ) -> None:
        """Register a local async handler for a concrete event type."""
        ...

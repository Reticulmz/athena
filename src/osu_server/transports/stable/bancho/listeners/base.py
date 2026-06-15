"""ListenerGroup - declarative local event listener registration.

Extends :class:`RouteGroup` to subscribe ``@listens``-decorated methods
to a local event bus in one call. Symmetric with :class:`HandlerGroup`.

Design ref: ListenerGroup component in c2s-handlers design.md
Requirements: 3.1, 3.2, 3.3, 1.5
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.transports.stable.bancho.routing import RouteGroup, route

if TYPE_CHECKING:
    from osu_server.infrastructure.messaging.local import LocalEventBus

listens = route
"""Alias for :func:`route` — use ``@listens(UserDisconnected)``."""

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class ListenerGroup(RouteGroup):
    """Base class for local event listener groups.

    Subclass this, decorate async methods with ``@listens(EventType)``,
    then call :meth:`register_all` to subscribe them to a local event bus.
    """

    def register_all(self, event_bus: LocalEventBus) -> None:
        """Subscribe all ``@listens``-decorated methods to the local bus.

        Logs ``listeners_registered`` on success with group name and count.
        Warns if the group has no listeners (Req 1.5).
        """
        count = 0
        for event_type, handler in self.get_routes():
            event_bus.subscribe(event_type, handler)  # pyright: ignore[reportArgumentType]
            count += 1

        group_name = type(self).__name__
        if count == 0:
            logger.warning("listeners_registered", group=group_name, count=0)
        else:
            logger.info("listeners_registered", group=group_name, count=count)

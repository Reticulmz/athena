"""HandlerGroup — declarative C2S packet handler registration.

Extends :class:`RouteGroup` to register ``@handles``-decorated methods
with a :class:`PacketDispatcher` in one call.

Design ref: HandlerGroup component in c2s-handlers design.md
Requirements: 2.1, 2.2, 2.3, 2.4, 1.5
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.transports.stable.bancho.routing import RouteGroup, route

if TYPE_CHECKING:
    from osu_server.transports.stable.bancho.dispatch import PacketDispatcher

handles = route
"""Alias for :func:`route` — use ``@handles(ClientPacketID.PONG)``."""

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class HandlerGroup(RouteGroup):
    """Base class for C2S packet handler groups.

    Subclass this, decorate async methods with ``@handles(ClientPacketID.XXX)``,
    then call :meth:`register_all` to wire them into a
    :class:`PacketDispatcher`.
    """

    def register_all(self, dispatcher: PacketDispatcher) -> None:
        """Register all ``@handles``-decorated methods with *dispatcher*.

        Logs ``handlers_registered`` on success with group name and count.
        Warns if the group has no handlers (Req 1.5).
        Raises :class:`DuplicateHandlerError` if *dispatcher* already has
        a handler for one of the packet IDs (Req 2.4).
        """
        count = 0
        for packet_id, handler in self.get_routes():
            _ = dispatcher.register(packet_id)(handler)  # pyright: ignore[reportArgumentType]
            count += 1

        group_name = type(self).__name__
        if count == 0:
            logger.warning("handlers_registered", group=group_name, count=0)
        else:
            logger.info("handlers_registered", group=group_name, count=count)

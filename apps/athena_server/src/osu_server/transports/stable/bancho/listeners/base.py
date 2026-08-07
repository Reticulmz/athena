"""stable Bancho local event listenerを宣言的に登録する基盤を提供する.

``@listens``でevent型へ関連付けたmethodをlocal event busへ一括subscribeする.
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
    """local event listener群の共通登録機能を提供する.

    subclassのasync methodを``@listens(EventType)``で宣言し,``register_all``で
    local event busへsubscribeする.
    """

    def register_all(self, event_bus: LocalEventBus) -> None:
        """宣言済みのlocal event listenerをevent busへsubscribeする.

        Args:
            event_bus (LocalEventBus): listenerを登録するlocal event bus.

        Returns:
            None: 登録数をlogへ記録し,呼び出し側へ値を返さずに完了する.
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

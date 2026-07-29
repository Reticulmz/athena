"""stable Bancho C2S handlerを宣言的に登録する基盤を提供する.

``@handles``でpacket IDへ関連付けたmethodを,PacketDispatcherへ一括登録する.
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
    """C2S packet handler群の共通登録機能を提供する.

    subclassのasync methodを``@handles(ClientPacketID.PONG)``で宣言し,
    ``register_all``でPacketDispatcherへ関連付ける.
    """

    def register_all(self, dispatcher: PacketDispatcher) -> None:
        """宣言済みのC2S handlerをPacketDispatcherへ登録する.

        Args:
            dispatcher (PacketDispatcher): handlerをdispatchする登録先.

        Returns:
            None: 登録数をlogへ記録し,呼び出し側へ値を返さずに完了する.

        Raises:
            DuplicateHandlerError: 同じpacket IDのhandlerが登録済みで,
                PacketDispatcher.registerが送出する場合.
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

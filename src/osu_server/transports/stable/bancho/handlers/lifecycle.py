"""LifecycleHandlers — PONG and EXIT C2S packet handlers.

Design ref: LifecycleHandlers component in c2s-handlers design.md
Requirements: 5.1, 5.2, 6.1, 6.2, 6.4, 6.5, 6.6
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID

if TYPE_CHECKING:
    from osu_server.infrastructure.messaging.interfaces import EventBus
    from osu_server.repositories.interfaces.session_store import SessionStore

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class LifecycleHandlers(HandlerGroup):
    """Handles PONG (keepalive) and EXIT (disconnect) C2S packets.

    PONG is a no-op; logging is handled by PacketDispatcher's
    QUIET_C2S_PACKETS mechanism at DEBUG level (Req 5.2).

    EXIT fires a ``UserDisconnected`` event and deletes the session.
    The try/finally pattern guarantees session deletion even if
    event firing fails (Req 6.6).
    """

    _session_store: SessionStore
    _event_bus: EventBus

    def __init__(
        self,
        session_store: SessionStore,
        event_bus: EventBus,
    ) -> None:
        self._session_store = session_store
        self._event_bus = event_bus

    @handles(ClientPacketID.PONG)
    async def handle_pong(self, _payload: bytes, _user_id: int) -> None:
        """Keepalive response — accept and do nothing (Req 5.1)."""

    @handles(ClientPacketID.EXIT)
    async def handle_exit(self, _payload: bytes, user_id: int) -> None:
        """Disconnect — fire event and delete session (Req 6.1, 6.2, 6.6).

        try block: fire ``UserDisconnected`` event.
        finally block: ``delete_by_user`` guarantees session cleanup.
        ``delete_by_user`` is idempotent — safe to call on already-deleted
        sessions (Req 6.5).
        """
        try:
            await self._event_bus.fire(UserDisconnected(user_id=user_id))
        finally:
            await self._session_store.delete_by_user(user_id)

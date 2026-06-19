"""PONG and EXIT packet handlers for stable bancho sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID

if TYPE_CHECKING:
    from osu_server.infrastructure.messaging.local import LocalEventBus
    from osu_server.repositories.interfaces.session_store import SessionLifecycleRuntime

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class LifecycleHandlers(HandlerGroup):
    """Handles PONG (keepalive) and EXIT (disconnect) C2S packets.

    PONG is a no-op; logging is handled by PacketDispatcher's quiet packet
    policy at DEBUG level.

    EXIT fires a ``UserDisconnected`` event and deletes the session.
    The try/finally pattern guarantees session deletion even if
    event firing fails.
    """

    _session_store: SessionLifecycleRuntime
    _event_bus: LocalEventBus

    def __init__(
        self,
        session_store: SessionLifecycleRuntime,
        event_bus: LocalEventBus,
    ) -> None:
        self._session_store = session_store
        self._event_bus = event_bus

    @handles(ClientPacketID.PONG)
    async def handle_pong(self, _payload: bytes, _user_id: int) -> None:
        """Accept a keepalive packet without changing durable state."""

    @handles(ClientPacketID.EXIT)
    async def handle_exit(self, _payload: bytes, user_id: int) -> None:
        """Fire a disconnect event and delete the active session.

        try block: fire ``UserDisconnected`` event.
        finally block: ``delete_by_user`` guarantees session cleanup.
        ``delete_by_user`` is idempotent and safe for already-deleted sessions.
        """
        try:
            await self._event_bus.fire(UserDisconnected(user_id=user_id))
        finally:
            await self._session_store.delete_by_user(user_id)

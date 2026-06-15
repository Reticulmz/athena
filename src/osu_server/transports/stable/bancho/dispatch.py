"""PacketDispatcher — decorator-driven C2S packet handler registry.

Design ref: PacketDispatcher component in bancho-protocol design.md
Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
Logging requirements: 5.1-5.4 (structured-logging spec)
"""

from collections.abc import Awaitable, Callable

import structlog

from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import DuplicateHandlerError

type PacketHandler = Callable[[bytes, int], Awaitable[None]]

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

QUIET_C2S_PACKETS: frozenset[ClientPacketID] = frozenset(
    {
        ClientPacketID.PONG,
        ClientPacketID.STATS_REQUEST,
        ClientPacketID.PRESENCE_REQUEST,
    }
)


class PacketDispatcher:
    """C2S packet handler registry and dispatcher.

    Handlers are registered via the :meth:`register` decorator and
    looked up by :class:`ClientPacketID` during dispatch.
    """

    __slots__: tuple[str, ...] = ("_handlers",)

    def __init__(self) -> None:
        self._handlers: dict[ClientPacketID, PacketHandler] = {}

    def register(self, packet_id: ClientPacketID) -> Callable[[PacketHandler], PacketHandler]:
        """Decorator that registers a handler for *packet_id*.

        Raises :class:`DuplicateHandlerError` if *packet_id* is already registered.
        """

        def decorator(func: PacketHandler) -> PacketHandler:
            if packet_id in self._handlers:
                msg = f"Duplicate handler for {packet_id.name} (id={packet_id.value})"
                raise DuplicateHandlerError(msg)
            self._handlers[packet_id] = func
            return func

        return decorator

    async def dispatch(self, packet_id: ClientPacketID, payload: bytes, user_id: int) -> None:
        """Call the registered handler for *packet_id*, with structured logging.

        The ``c2s_packet`` event is emitted **after** the handler completes so
        that a successful log entry is never produced for a failed handler.

        Logging behaviour:
        - Registered + quiet packet → ``logger.debug("c2s_packet", ...)``
        - Registered + normal packet → ``logger.info("c2s_packet", ...)``
        - Unregistered packet → ``logger.debug("c2s_unhandled", ...)``
        """
        handler = self._handlers.get(packet_id)
        if handler is None:
            logger.debug("c2s_unhandled", packet=packet_id.name, size=len(payload))
            return

        await handler(payload, user_id)

        if packet_id in QUIET_C2S_PACKETS:
            logger.debug("c2s_packet", packet=packet_id.name, size=len(payload))
        else:
            logger.info("c2s_packet", packet=packet_id.name, size=len(payload))

    def get_handlers(self) -> dict[ClientPacketID, PacketHandler]:
        """Return a read-only copy of all registered handlers."""
        return dict(self._handlers)


# Module-level default instance for decorator-based handler registration.
dispatcher: PacketDispatcher = PacketDispatcher()

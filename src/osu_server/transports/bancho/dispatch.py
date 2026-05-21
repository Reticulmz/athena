"""PacketDispatcher — decorator-driven C2S packet handler registry.

Design ref: PacketDispatcher component in bancho-protocol design.md
Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from collections.abc import Awaitable, Callable

from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.errors import DuplicateHandlerError

type PacketHandler = Callable[..., Awaitable[None]]


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

    async def dispatch(
        self, packet_id: ClientPacketID, payload: bytes, *args: object, **kwargs: object
    ) -> None:
        """Call the registered handler for *packet_id*.

        If no handler is registered for *packet_id*, silently returns.
        """
        handler = self._handlers.get(packet_id)
        if handler is not None:
            await handler(payload, *args, **kwargs)

    def get_handlers(self) -> dict[ClientPacketID, PacketHandler]:
        """Return a read-only copy of all registered handlers."""
        return dict(self._handlers)

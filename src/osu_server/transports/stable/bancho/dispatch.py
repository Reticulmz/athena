"""Stable Bancho の C2S packet handler を登録して dispatch する."""

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
        ClientPacketID.PRESENCE_REQUEST_ALL,
    }
)


class PacketDispatcher:
    """C2S packet handler の registry と dispatch を提供する.

    Attributes:
        _handlers (dict[ClientPacketID, PacketHandler]): packet ID ごとに登録した handler.
    """

    __slots__: tuple[str, ...] = ("_handlers",)

    def __init__(self) -> None:
        """空の C2S packet handler registry を初期化する."""
        self._handlers: dict[ClientPacketID, PacketHandler] = {}

    def register(self, packet_id: ClientPacketID) -> Callable[[PacketHandler], PacketHandler]:
        """指定した packet ID 用の handler を登録する decorator を返す.

        Args:
            packet_id (ClientPacketID): 登録対象の C2S packet ID.

        Returns:
            Callable[[PacketHandler], PacketHandler]: handler を登録してそのまま返す decorator.

        Raises:
            DuplicateHandlerError: packet_id に既存 handler が登録済みの場合.
        """

        def decorator(func: PacketHandler) -> PacketHandler:
            """指定した handler を packet ID に関連付けて返す.

            Args:
                func (PacketHandler): payload と user ID を受け取る非同期 handler.

            Returns:
                PacketHandler: registry へ登録した元の handler.

            Raises:
                DuplicateHandlerError: packet ID に既存 handler が登録済みの場合.
            """
            if packet_id in self._handlers:
                msg = f"Duplicate handler for {packet_id.name} (id={packet_id.value})"
                raise DuplicateHandlerError(msg)
            self._handlers[packet_id] = func
            return func

        return decorator

    async def dispatch(self, packet_id: ClientPacketID, payload: bytes, user_id: int) -> None:
        """登録済み C2S handler を呼び出して結果を structured log に記録する.

        Args:
            packet_id (ClientPacketID): dispatch 対象の C2S packet ID.
            payload (bytes): packet header を除いた wire payload.
            user_id (int): packet を送った認証済み user の ID.

        Returns:
            None: handler を完了させるか未登録 packet を記録して値を返さない.

        Notes:
            handler 成功後だけ c2s_packet を記録する. QUIET_C2S_PACKETS の packet と
            未登録 packet は debug level で記録する.
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
        """登録済み handler の独立した snapshot を返す.

        Returns:
            dict[ClientPacketID, PacketHandler]: registry の後続変更を共有しない辞書.
        """
        return dict(self._handlers)


# Module-level default instance for decorator-based handler registration.
dispatcher: PacketDispatcher = PacketDispatcher()

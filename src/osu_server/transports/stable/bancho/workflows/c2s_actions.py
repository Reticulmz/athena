"""Stable C2S packet stream execution policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.reader import read_packets

if TYPE_CHECKING:
    from osu_server.transports.stable.bancho.dispatch import PacketDispatcher

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(slots=True, frozen=True)
class C2SActionExecutionResult:
    """Result of executing one stable C2S request body."""

    packet_count: int


class C2SActionExecutor:
    """Owns packet-stream parse and handler failure policy for polling."""

    _packet_dispatcher: PacketDispatcher

    def __init__(self, packet_dispatcher: PacketDispatcher) -> None:
        self._packet_dispatcher = packet_dispatcher

    async def execute(self, *, body: bytes, user_id: int) -> C2SActionExecutionResult:
        """Parse and dispatch all C2S packets in one request body."""
        if not body:
            return C2SActionExecutionResult(packet_count=0)

        try:
            packets = read_packets(body)
        except PacketReadError:
            logger.error("c2s_parse_error", exc_info=True)
            return C2SActionExecutionResult(packet_count=0)

        packet_count = 0
        for packet_id, payload in packets:
            packet_count += 1
            try:
                await self._packet_dispatcher.dispatch(packet_id, payload, user_id)
            except Exception:
                logger.error(
                    "c2s_handler_error",
                    packet=packet_id.name,
                    payload_size=len(payload),
                    exc_info=True,
                )

        return C2SActionExecutionResult(packet_count=packet_count)


__all__ = ["C2SActionExecutionResult", "C2SActionExecutor"]

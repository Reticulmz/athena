"""Stable Bancho polling request 内の C2S packet stream を実行する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import structlog

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.reader import read_packets

if TYPE_CHECKING:
    from osu_server.transports.stable.bancho.dispatch import PacketDispatcher

logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


@dataclass(slots=True, frozen=True)
class C2SActionExecutionResult:
    """1 個の stable C2S request body を実行した結果を表す.

    Attributes:
        packet_count (int): parse に成功して dispatch を試行した packet の数.
    """

    packet_count: int


class C2SActionExecutor:
    """polling 用 C2S packet stream の解析と handler failure policy を所有する.

    Attributes:
        _packet_dispatcher (PacketDispatcher): C2S packet ごとの handler を呼び出す dispatcher.
    """

    _packet_dispatcher: PacketDispatcher

    def __init__(self, packet_dispatcher: PacketDispatcher) -> None:
        """C2S packet を dispatch する dependency を設定する.

        Args:
            packet_dispatcher (PacketDispatcher): packet handler registry と dispatcher.
        """
        self._packet_dispatcher = packet_dispatcher

    async def execute(self, *, body: bytes, user_id: int) -> C2SActionExecutionResult:
        """受け取った request body 内の C2S packet を順番に dispatch する.

        Args:
            body (bytes): polling request から受け取った C2S packet stream.
            user_id (int): packet を送った認証済み user の ID.

        Returns:
            C2SActionExecutionResult: dispatch を試行した packet 数.

        Notes:
            空 body は packet_count 0 で完了する. parse error は記録して全 dispatch を省略し,
            individual handler error は記録して残りの packet の処理を継続する.
        """
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

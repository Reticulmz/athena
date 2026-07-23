"""stable Bancho sessionのPONGとEXIT C2S packetを処理する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID

if TYPE_CHECKING:
    from osu_server.infrastructure.messaging.local import LocalEventBus
    from osu_server.repositories.interfaces.session_store import SessionLifecycleRuntime

logger: structlog.stdlib.BoundLogger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)


class LifecycleHandlers(HandlerGroup):
    """PONG keepaliveとEXIT disconnectのC2S packetを処理する.

    Attributes:
        _session_store (SessionLifecycleRuntime): active sessionを削除するruntime store.
        _event_bus (LocalEventBus): disconnect domain eventを発行するlocal event bus.

    Notes:
        EXITではevent発行が失敗しても``finally``でsession削除を実行する。
    """

    _session_store: SessionLifecycleRuntime
    _event_bus: LocalEventBus

    def __init__(
        self,
        session_store: SessionLifecycleRuntime,
        event_bus: LocalEventBus,
    ) -> None:
        """Session lifecycle依存を初期化する.

        Args:
            session_store (SessionLifecycleRuntime): session削除を行うruntime store.
            event_bus (LocalEventBus): UserDisconnectedを発行するlocal event bus.
        """
        self._session_store = session_store
        self._event_bus = event_bus

    @handles(ClientPacketID.PONG)
    async def handle_pong(self, _payload: bytes, _user_id: int) -> None:
        """PONG keepaliveを状態変更なしで受理する.

        Args:
            _payload (bytes): 内容を利用しないPONG packet payload.
            _user_id (int): 内容を利用しない送信元user ID.

        Returns:
            None: keepaliveを受理し、呼び出し側へ値を返さずに完了する.
        """

    @handles(ClientPacketID.EXIT)
    async def handle_exit(self, _payload: bytes, user_id: int) -> None:
        """Disconnect eventを発行してactive sessionを削除する.

        Args:
            _payload (bytes): 内容を利用しないEXIT packet payload.
            user_id (int): 切断する認証済みuserのID.

        Returns:
            None: event発行後にsession削除を行い、値を返さずに完了する.

        Notes:
            event発行の例外は伝播するが、``finally``によりsession削除は必ず試行する。
        """
        try:
            await self._event_bus.fire(UserDisconnected(user_id=user_id))
        finally:
            await self._session_store.delete_by_user(user_id)

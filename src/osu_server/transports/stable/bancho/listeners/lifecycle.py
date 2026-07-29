"""stable Bancho user lifecycle eventをpresence packet fan-outへ適応する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog

from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.events.users import UserConnected, UserDisconnected
from osu_server.services.queries.identity import ListActiveSessionsQueryInput
from osu_server.transports.stable.bancho.listeners.base import ListenerGroup, listens
from osu_server.transports.stable.bancho.workflows.presence_roster import (
    StablePresenceRoster,
)

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.identity import ListActiveSessionsQuery

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class LifecycleListeners(ListenerGroup):
    """user lifecycle eventをstable presence packet fan-outへ変換する.

    Attributes:
        _active_sessions_query (ListActiveSessionsQuery): online sessionを取得するquery.
        _packet_queue (PacketQueue): S2C packetをrecipientへenqueueするqueue.
        _presence_roster (StablePresenceRoster): presenceとquitのfan-outを組み立てるworkflow.
        _stable_user_status_store (StableUserStatusStore | None):
            connected userのcurrent modeを取得するstore.
    """

    _active_sessions_query: ListActiveSessionsQuery
    _packet_queue: PacketQueue
    _presence_roster: StablePresenceRoster
    _stable_user_status_store: StableUserStatusStore | None

    def __init__(
        self,
        active_sessions_query: ListActiveSessionsQuery,
        packet_queue: PacketQueue,
        stable_user_status_store: StableUserStatusStore | None = None,
        presence_roster: StablePresenceRoster | None = None,
    ) -> None:
        """Lifecycle presence fan-outの依存を初期化する.

        Args:
            active_sessions_query (ListActiveSessionsQuery): online sessionを取得するquery.
            packet_queue (PacketQueue): S2C packetを配信するqueue.
            stable_user_status_store (StableUserStatusStore | None):
                current mode読取用のoptional store.
            presence_roster (StablePresenceRoster | None): fan-out構築workflow.
                Noneなら既定instanceを使う.
        """
        self._active_sessions_query = active_sessions_query
        self._packet_queue = packet_queue
        self._stable_user_status_store = stable_user_status_store
        self._presence_roster = presence_roster or StablePresenceRoster()

    @listens(UserConnected)
    async def on_user_connected(self, event: UserConnected) -> None:
        """接続userのUSER_PRESENCEを既存online userへfan-outする.

        Args:
            event (UserConnected): 接続したuserを表すdomain event.

        Returns:
            None: recipientがある場合にUSER_PRESENCEをenqueueし,値を返さずに完了する.

        Notes:
            active sessionに存在しないuserと接続user自身にはpacketを配信しない.
        """
        active_sessions = await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        play_mode = await self._play_mode_for_user(event.user_id)
        fanout = self._presence_roster.connected_user_fanout(
            user_id=event.user_id,
            active_sessions=active_sessions.sessions,
            play_mode=play_mode,
        )
        if fanout is None:
            return
        for recipient_user_id in fanout.recipient_user_ids:
            await self._packet_queue.enqueue(recipient_user_id, fanout.packet)

    async def _play_mode_for_user(self, user_id: int) -> int:
        """Connected userの保存済みstable play modeを正規化して取得する.

        Args:
            user_id (int): modeを取得するconnected userのID.

        Returns:
            int: 有効なstable play mode. store未設定,値なし,読取失敗,不正値ではosu mode.
        """
        if self._stable_user_status_store is None:
            return StableMode.Osu.value
        try:
            play_mode = await self._stable_user_status_store.get_play_mode(user_id)
        except Exception:
            logger.exception(
                "stable_lifecycle_status_read_failed",
                user_id=user_id,
            )
            return StableMode.Osu.value
        if play_mode is None:
            return StableMode.Osu.value
        try:
            return StableMode(play_mode).value
        except ValueError:
            return StableMode.Osu.value

    @listens(UserDisconnected)
    async def on_user_disconnected(self, event: UserDisconnected) -> None:
        """切断userのUSER_QUITをonline recipientへfan-outする.

        Args:
            event (UserDisconnected): 切断したuserを表すdomain event.

        Returns:
            None: recipientごとにUSER_QUITをenqueueし,呼び出し側へ値を返さずに完了する.

        Notes:
            切断user自身には自身のquit通知を配信しない.
        """
        active_sessions = await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        fanout = self._presence_roster.disconnected_user_fanout(
            user_id=event.user_id,
            active_sessions=active_sessions.sessions,
        )
        for recipient_user_id in fanout.recipient_user_ids:
            await self._packet_queue.enqueue(recipient_user_id, fanout.packet)

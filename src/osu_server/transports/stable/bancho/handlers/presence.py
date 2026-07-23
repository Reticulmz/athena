"""stable Banchoのonline presence request C2S packetを処理する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog

from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.services.queries.identity import (
    GetActiveSessionsByUserIdsQueryInput,
    ListActiveSessionsQueryInput,
)
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.mappers.presence import (
    bot_presence_packet,
    online_session_presence_packet_for_mode,
)
from osu_server.transports.stable.bancho.protocol.c2s import (
    parse_presence_request_all_payload,
    parse_presence_request_payload,
)
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.s2c.login import user_presence_bundle

if TYPE_CHECKING:
    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.identity import (
        GetActiveSessionsByUserIdsQuery,
        ListActiveSessionsQuery,
    )

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class PresenceHandlers(HandlerGroup):
    """presence request C2S packetをonline rosterのS2C packetへ変換する.

    Attributes:
        _active_sessions_query (ListActiveSessionsQuery): 全online sessionを取得するquery.
        _active_sessions_by_user_ids_query (GetActiveSessionsByUserIdsQuery):
            指定userのsessionを取得するquery.
        _packet_queue (PacketQueue): presence packetをrequesterへenqueueするqueue.
        _bot_identity (SystemUserIdentity): rosterへ常に含めるBanchoBot identity.
        _stable_user_status_store (StableUserStatusStore | None):
            userごとのcurrent modeを取得するstore.
    """

    _active_sessions_query: ListActiveSessionsQuery
    _active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQuery
    _packet_queue: PacketQueue
    _bot_identity: SystemUserIdentity
    _stable_user_status_store: StableUserStatusStore | None

    def __init__(
        self,
        *,
        active_sessions_query: ListActiveSessionsQuery,
        active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQuery,
        packet_queue: PacketQueue,
        bot_identity: SystemUserIdentity | None = None,
        stable_user_status_store: StableUserStatusStore | None = None,
    ) -> None:
        """Presence requestを処理する依存を初期化する.

        Args:
            active_sessions_query (ListActiveSessionsQuery): 全online sessionを取得するquery.
            active_sessions_by_user_ids_query (GetActiveSessionsByUserIdsQuery):
                指定userのsessionを取得するquery.
            packet_queue (PacketQueue): S2C packetをenqueueするqueue.
            bot_identity (SystemUserIdentity | None): rosterに使うBanchoBot identity.
                Noneなら既定値を使う.
            stable_user_status_store (StableUserStatusStore | None):
                current modeを取得するoptional store.
        """
        self._active_sessions_query = active_sessions_query
        self._active_sessions_by_user_ids_query = active_sessions_by_user_ids_query
        self._packet_queue = packet_queue
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY
        self._stable_user_status_store = stable_user_status_store

    @handles(ClientPacketID.PRESENCE_REQUEST)
    async def handle_presence_request(self, payload: bytes, user_id: int) -> None:
        """PRESENCE_REQUESTの指定online userをUSER_PRESENCEで返す.

        Args:
            payload (bytes): request対象user ID群を含むC2S packet payload.
            user_id (int): presence情報を要求した認証済みuserのID.

        Returns:
            None: online targetのpresence packetをenqueueして値を返さずに完了する.

        Notes:
            offline targetは除外し、BanchoBotはrequesterのcurrent modeで返す。
        """
        requested_user_ids = _parse_presence_request(payload)
        if requested_user_ids is None:
            return

        lookup_user_ids = tuple(
            user_id
            for user_id in dict.fromkeys(requested_user_ids)
            if user_id != self._bot_identity.user_id
        )
        active_sessions = await self._active_sessions_by_user_ids_query.execute(
            GetActiveSessionsByUserIdsQueryInput(user_ids=lookup_user_ids)
        )
        sessions_by_user_id = {session.user_id: session for session in active_sessions.sessions}
        play_modes_by_user_id = await self._play_modes_by_user_id(lookup_user_ids)
        requester_play_mode = await self._requester_play_mode(user_id)
        packets: list[bytes] = []
        for requested_user_id in requested_user_ids:
            if requested_user_id == self._bot_identity.user_id:
                packets.append(
                    bot_presence_packet(
                        self._bot_identity,
                        play_mode=requester_play_mode,
                    )
                )
                continue

            session = sessions_by_user_id.get(requested_user_id)
            if session is not None:
                packets.append(
                    online_session_presence_packet_for_mode(
                        session,
                        play_mode=_stable_play_mode_for_user(
                            requested_user_id,
                            play_modes_by_user_id,
                        ),
                    )
                )

        if not packets:
            return

        await self._packet_queue.enqueue(user_id, *packets)

    @handles(ClientPacketID.PRESENCE_REQUEST_ALL)
    async def handle_presence_request_all(self, payload: bytes, user_id: int) -> None:
        """PRESENCE_REQUEST_ALLでonline roster全体をUSER_PRESENCEとして返す.

        Args:
            payload (bytes): reserved int32を含むC2S packet payload.
            user_id (int): rosterを要求した認証済みuserのID.

        Returns:
            None: online user、BanchoBot、roster bundleをenqueueして値を返さずに完了する.

        Notes:
            不正なreserved payloadはqueryとenqueueを行わずdropする。
        """
        if not _parse_presence_request_all(payload):
            return

        active_sessions = await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        session_user_ids = tuple(session.user_id for session in active_sessions.sessions)
        play_modes_by_user_id = await self._play_modes_by_user_id(session_user_ids)
        requester_play_mode = await self._requester_play_mode(user_id)
        roster_ids = list(
            dict.fromkeys(
                [
                    self._bot_identity.user_id,
                    *(session.user_id for session in active_sessions.sessions),
                ]
            )
        )
        packets = (
            bot_presence_packet(self._bot_identity, play_mode=requester_play_mode),
            *(
                online_session_presence_packet_for_mode(
                    session,
                    play_mode=_stable_play_mode_for_user(
                        session.user_id,
                        play_modes_by_user_id,
                    ),
                )
                for session in active_sessions.sessions
            ),
            user_presence_bundle(roster_ids),
        )
        await self._packet_queue.enqueue(user_id, *packets)

    async def _play_modes_by_user_id(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """指定userの保存済みstable play modeを取得する.

        Args:
            user_ids (tuple[int, ...]): modeを取得するonline user ID群.

        Returns:
            dict[int, int]: user IDからstable play modeへの対応.
                store未設定または読取失敗時は空dict.
        """
        if self._stable_user_status_store is None:
            return {}
        try:
            return await self._stable_user_status_store.get_play_modes(user_ids)
        except Exception:
            logger.exception(
                "stable_presence_request_status_read_failed",
                requested_user_ids=user_ids,
            )
            return {}

    async def _requester_play_mode(self, user_id: int) -> int:
        """Presence requesterに表示するBanchoBotのstable play modeを取得する.

        Args:
            user_id (int): requesterの認証済みuser ID.

        Returns:
            int: 正規化済みstable play mode. statusがないか読取失敗時はosu mode.
        """
        if self._stable_user_status_store is None:
            return StableMode.Osu.value
        try:
            play_mode = await self._stable_user_status_store.get_play_mode(user_id)
        except Exception:
            logger.exception(
                "stable_presence_requester_status_read_failed",
                user_id=user_id,
            )
            return StableMode.Osu.value
        return _stable_play_mode(play_mode)


def _stable_play_mode_for_user(
    user_id: int,
    play_modes_by_user_id: dict[int, int],
) -> int:
    """指定userのstable play modeを正規化して返す.

    Args:
        user_id (int): modeを選択するtarget user ID.
        play_modes_by_user_id (dict[int, int]): user IDから保存済みmodeへの対応.

    Returns:
        int: 有効なstable play mode. 値がないか不正な場合はosu mode.
    """
    play_mode = play_modes_by_user_id.get(user_id, StableMode.Osu.value)
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


def _stable_play_mode(play_mode: int | None) -> int:
    """optionalなplay modeを有効なstable modeへ正規化する.

    Args:
        play_mode (int | None): status storeから得た可能性のあるmode値.

    Returns:
        int: 有効なstable play mode. Noneまたは不正値の場合はosu mode.
    """
    if play_mode is None:
        return StableMode.Osu.value
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


def _parse_presence_request(payload: bytes) -> tuple[int, ...] | None:
    """PRESENCE_REQUEST payloadを安全にparseする.

    Args:
        payload (bytes): target user ID群を含むC2S packet payload.

    Returns:
        tuple[int, ...] | None: 要求されたuser ID群. payloadが不正な場合はNone.
    """
    try:
        return parse_presence_request_payload(payload)
    except PacketReadError as exc:
        logger.warning(
            "c2s_malformed_payload",
            packet="PRESENCE_REQUEST",
            payload_size=len(payload),
            reason=str(exc),
        )
        return None


def _parse_presence_request_all(payload: bytes) -> bool:
    """PRESENCE_REQUEST_ALLのreserved payloadを検証する.

    Args:
        payload (bytes): reserved int32を含むC2S packet payload.

    Returns:
        bool: payloadをparseできた場合はTrue. 不正な場合はFalse.
    """
    try:
        parse_presence_request_all_payload(payload)
    except PacketReadError as exc:
        logger.warning(
            "c2s_malformed_payload",
            packet="PRESENCE_REQUEST_ALL",
            payload_size=len(payload),
            reason=str(exc),
        )
        return False
    return True


__all__ = ["PresenceHandlers"]

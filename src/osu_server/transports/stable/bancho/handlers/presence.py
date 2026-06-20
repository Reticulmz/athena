"""Stable online presence request packet handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog

from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.services.queries.identity import (
    GetActiveSessionsByUserIdsQueryInput,
    ListActiveSessionsQueryInput,
)
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.mappers.presence import (
    bot_presence_packet,
    online_session_presence_packet,
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
    from osu_server.services.queries.identity import (
        GetActiveSessionsByUserIdsQuery,
        ListActiveSessionsQuery,
    )

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class PresenceHandlers(HandlerGroup):
    """C2S presence request handlers."""

    _active_sessions_query: ListActiveSessionsQuery
    _active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQuery
    _packet_queue: PacketQueue
    _bot_identity: SystemUserIdentity

    def __init__(
        self,
        *,
        active_sessions_query: ListActiveSessionsQuery,
        active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQuery,
        packet_queue: PacketQueue,
        bot_identity: SystemUserIdentity | None = None,
    ) -> None:
        self._active_sessions_query = active_sessions_query
        self._active_sessions_by_user_ids_query = active_sessions_by_user_ids_query
        self._packet_queue = packet_queue
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY

    @handles(ClientPacketID.PRESENCE_REQUEST)
    async def handle_presence_request(self, payload: bytes, user_id: int) -> None:
        """PRESENCE_REQUEST (97) - send USER_PRESENCE for requested online users."""
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
        packets: list[bytes] = []
        for requested_user_id in requested_user_ids:
            if requested_user_id == self._bot_identity.user_id:
                packets.append(bot_presence_packet(self._bot_identity))
                continue

            session = sessions_by_user_id.get(requested_user_id)
            if session is not None:
                packets.append(online_session_presence_packet(session))

        if not packets:
            return

        await self._packet_queue.enqueue(user_id, *packets)

    @handles(ClientPacketID.PRESENCE_REQUEST_ALL)
    async def handle_presence_request_all(self, payload: bytes, user_id: int) -> None:
        """PRESENCE_REQUEST_ALL (98) - send USER_PRESENCE for online users."""
        if not _parse_presence_request_all(payload):
            return

        active_sessions = await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        roster_ids = list(
            dict.fromkeys(
                [
                    self._bot_identity.user_id,
                    *(session.user_id for session in active_sessions.sessions),
                ]
            )
        )
        packets = (
            bot_presence_packet(self._bot_identity),
            *(online_session_presence_packet(session) for session in active_sessions.sessions),
            user_presence_bundle(roster_ids),
        )
        await self._packet_queue.enqueue(user_id, *packets)


def _parse_presence_request(payload: bytes) -> tuple[int, ...] | None:
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

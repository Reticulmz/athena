"""LifecycleListeners — user lifecycle event to stable presence broadcast.

Subscribes to user lifecycle domain events and enqueues client-visible
presence packets to active online users.

Design ref: LifecycleListeners component in c2s-handlers design.md
Requirements: 6.3, 9.1
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from osu_server.domain.events.users import UserConnected, UserDisconnected
from osu_server.services.queries.identity import ListActiveSessionsQueryInput
from osu_server.transports.stable.bancho.listeners.base import ListenerGroup, listens
from osu_server.transports.stable.bancho.mappers.presence import (
    online_session_presence_packet,
)
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.writer import write_packet

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.services.queries.identity import ListActiveSessionsQuery

_INT32_FMT = struct.Struct("<i")


class LifecycleListeners(ListenerGroup):
    """Listens for user lifecycle domain events and broadcasts S2C packets.

    Currently handles:
    - ``UserConnected`` → ``USER_PRESENCE`` to all other online users
    - ``UserDisconnected`` → ``USER_QUIT`` to all online users
    """

    _active_sessions_query: ListActiveSessionsQuery
    _packet_queue: PacketQueue

    def __init__(
        self,
        active_sessions_query: ListActiveSessionsQuery,
        packet_queue: PacketQueue,
    ) -> None:
        self._active_sessions_query = active_sessions_query
        self._packet_queue = packet_queue

    @listens(UserConnected)
    async def on_user_connected(self, event: UserConnected) -> None:
        """Broadcast the connected user's USER_PRESENCE to other online users."""
        active_sessions = await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        connected_session = next(
            (session for session in active_sessions.sessions if session.user_id == event.user_id),
            None,
        )
        if connected_session is None:
            return

        presence_packet = online_session_presence_packet(connected_session)
        for session in active_sessions.sessions:
            if session.user_id != event.user_id:
                await self._packet_queue.enqueue(session.user_id, presence_packet)

    @listens(UserDisconnected)
    async def on_user_disconnected(self, event: UserDisconnected) -> None:
        """Broadcast USER_QUIT to all online users.

        The disconnecting user is excluded from the broadcast —
        they don't need their own quit notification (Req 6.3).
        """
        active_sessions = await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        quit_packet = write_packet(
            ServerPacketID.USER_QUIT,
            _INT32_FMT.pack(event.user_id),
        )

        for session in active_sessions.sessions:
            if session.user_id != event.user_id:
                await self._packet_queue.enqueue(session.user_id, quit_packet)

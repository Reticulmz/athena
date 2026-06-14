"""LifecycleListeners — UserDisconnected → USER_QUIT broadcast.

Subscribes to :class:`UserDisconnected` domain events and enqueues
``USER_QUIT`` S2C packets to all online users (excluding the
disconnecting user).

Design ref: LifecycleListeners component in c2s-handlers design.md
Requirements: 6.3, 9.1
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from osu_server.domain.events.users import UserDisconnected
from osu_server.services.queries.identity import ListOnlineUsersQueryInput
from osu_server.transports.bancho.listeners.base import ListenerGroup, listens
from osu_server.transports.bancho.protocol.enums import ServerPacketID
from osu_server.transports.bancho.protocol.writer import write_packet

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.services.queries.identity import ListOnlineUsersQuery

_INT32_FMT = struct.Struct("<i")


class LifecycleListeners(ListenerGroup):
    """Listens for user lifecycle domain events and broadcasts S2C packets.

    Currently handles:
    - ``UserDisconnected`` → ``USER_QUIT`` to all online users
    """

    _online_users_query: ListOnlineUsersQuery
    _packet_queue: PacketQueue

    def __init__(
        self,
        online_users_query: ListOnlineUsersQuery,
        packet_queue: PacketQueue,
    ) -> None:
        self._online_users_query = online_users_query
        self._packet_queue = packet_queue

    @listens(UserDisconnected)
    async def on_user_disconnected(self, event: UserDisconnected) -> None:
        """Broadcast USER_QUIT to all online users.

        The disconnecting user is excluded from the broadcast —
        they don't need their own quit notification (Req 6.3).
        """
        online_users = await self._online_users_query.execute(ListOnlineUsersQueryInput())
        quit_packet = write_packet(
            ServerPacketID.USER_QUIT,
            _INT32_FMT.pack(event.user_id),
        )

        for uid in online_users.user_ids:
            if uid != event.user_id:
                await self._packet_queue.enqueue(uid, quit_packet)

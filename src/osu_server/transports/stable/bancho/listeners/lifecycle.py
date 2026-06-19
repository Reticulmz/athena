"""User lifecycle event listeners for stable presence broadcasts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.events.users import UserConnected, UserDisconnected
from osu_server.services.queries.identity import ListActiveSessionsQueryInput
from osu_server.transports.stable.bancho.listeners.base import ListenerGroup, listens
from osu_server.transports.stable.bancho.workflows.presence_roster import (
    StablePresenceRoster,
)

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.services.queries.identity import ListActiveSessionsQuery


class LifecycleListeners(ListenerGroup):
    """Listens for user lifecycle domain events and broadcasts S2C packets.

    Currently handles:
    - ``UserConnected``: ``USER_PRESENCE`` to all other online users
    - ``UserDisconnected``: ``USER_QUIT`` to all online users
    """

    _active_sessions_query: ListActiveSessionsQuery
    _packet_queue: PacketQueue
    _presence_roster: StablePresenceRoster

    def __init__(
        self,
        active_sessions_query: ListActiveSessionsQuery,
        packet_queue: PacketQueue,
        presence_roster: StablePresenceRoster | None = None,
    ) -> None:
        self._active_sessions_query = active_sessions_query
        self._packet_queue = packet_queue
        self._presence_roster = presence_roster or StablePresenceRoster()

    @listens(UserConnected)
    async def on_user_connected(self, event: UserConnected) -> None:
        """Broadcast the connected user's USER_PRESENCE to other online users."""
        active_sessions = await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        fanout = self._presence_roster.connected_user_fanout(
            user_id=event.user_id,
            active_sessions=active_sessions.sessions,
        )
        if fanout is None:
            return
        for recipient_user_id in fanout.recipient_user_ids:
            await self._packet_queue.enqueue(recipient_user_id, fanout.packet)

    @listens(UserDisconnected)
    async def on_user_disconnected(self, event: UserDisconnected) -> None:
        """Broadcast USER_QUIT to all online users.

        The disconnecting user is excluded from the broadcast because stable
        clients do not need their own quit notification.
        """
        active_sessions = await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        fanout = self._presence_roster.disconnected_user_fanout(
            user_id=event.user_id,
            active_sessions=active_sessions.sessions,
        )
        for recipient_user_id in fanout.recipient_user_ids:
            await self._packet_queue.enqueue(recipient_user_id, fanout.packet)

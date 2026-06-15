"""Bancho local listeners - subscribe to local events and enqueue S2C packets.

Provides ``setup_listeners`` which creates and registers all bancho
listener groups with the local event bus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.transports.stable.bancho.listeners.chat import ChatListeners
from osu_server.transports.stable.bancho.listeners.lifecycle import LifecycleListeners

if TYPE_CHECKING:
    from osu_server.infrastructure.messaging.local import LocalEventBus
    from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.services.queries.identity import ListOnlineUsersQuery


def setup_listeners(
    eventbus: LocalEventBus,
    packet_queue: PacketQueue,
    online_users_query: ListOnlineUsersQuery,
    channel_state: ChannelStateStore,
) -> None:
    """Register all Bancho local event listeners.

    Called during application startup (lifespan).  Creates listener group
    instances and delegates to their ``register_all`` methods.
    """
    lifecycle = LifecycleListeners(
        online_users_query=online_users_query,
        packet_queue=packet_queue,
    )
    chat = ChatListeners(
        channel_state=channel_state,
    )

    lifecycle.register_all(eventbus)
    chat.register_all(eventbus)

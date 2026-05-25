"""Bancho event listeners — subscribe to domain events and enqueue S2C packets.

Provides ``setup_listeners`` which creates and registers all bancho
listener groups with the EventBus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.transports.bancho.listeners.lifecycle import LifecycleListeners

if TYPE_CHECKING:
    from osu_server.infrastructure.messaging.interfaces import EventBus
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.services.online_users import OnlineUsersService


def setup_listeners(
    eventbus: EventBus,
    packet_queue: PacketQueue,
    online_users: OnlineUsersService,
) -> None:
    """Register all Bancho event listeners with the EventBus.

    Called during application startup (lifespan).  Creates listener group
    instances and delegates to their ``register_all`` methods.
    """
    lifecycle = LifecycleListeners(
        online_users=online_users,
        packet_queue=packet_queue,
    )
    lifecycle.register_all(eventbus)

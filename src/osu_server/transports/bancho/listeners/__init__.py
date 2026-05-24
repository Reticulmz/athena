"""Bancho event listeners — subscribe to domain events and enqueue S2C packets.

Concrete listeners (e.g. ``BanchoChatListener``) will be added by
subsequent feature specs (c2s-handlers, etc.) and registered here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.infrastructure.messaging.interfaces import EventBus
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue


def setup_listeners(eventbus: EventBus, packet_queue: PacketQueue) -> None:
    """Register all Bancho event listeners with the EventBus.

    Called during application startup (lifespan).  Individual listeners
    are added here as they are implemented by subsequent specs.
    """
    _ = eventbus
    _ = packet_queue

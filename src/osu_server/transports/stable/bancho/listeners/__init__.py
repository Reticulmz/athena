"""Bancho local listeners - subscribe to local events and enqueue S2C packets.

Provides ``setup_listeners`` which creates and registers all bancho
listener groups with the local event bus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.transports.stable.bancho.listeners.chat import ChatListeners
from osu_server.transports.stable.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.stable.bancho.listeners.user_stats import UserStatsListeners

if TYPE_CHECKING:
    from osu_server.infrastructure.messaging.local import LocalEventBus
    from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.identity import ListActiveSessionsQuery
    from osu_server.services.queries.scores import CurrentUserStatsQuery


def setup_listeners(
    eventbus: LocalEventBus,
    packet_queue: PacketQueue,
    active_sessions_query: ListActiveSessionsQuery,
    channel_state: ChannelStateStore,
    current_user_stats_query: CurrentUserStatsQuery,
    stable_user_status_store: StableUserStatusStore | None = None,
) -> None:
    """Register all Bancho local event listeners.

    Called during application startup (lifespan).  Creates listener group
    instances and delegates to their ``register_all`` methods.
    """
    lifecycle = LifecycleListeners(
        active_sessions_query=active_sessions_query,
        packet_queue=packet_queue,
        stable_user_status_store=stable_user_status_store,
    )
    chat = ChatListeners(
        channel_state=channel_state,
    )
    user_stats = UserStatsListeners(
        packet_queue=packet_queue,
        current_user_stats_query=current_user_stats_query,
        stable_user_status_store=stable_user_status_store,
    )

    lifecycle.register_all(eventbus)
    chat.register_all(eventbus)
    user_stats.register_all(eventbus)

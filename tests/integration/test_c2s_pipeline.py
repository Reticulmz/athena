"""Integration tests for C2S handler pipeline (Task 5.1, Req 9.2).

Tests the full handler/listener integration with real (in-memory)
implementations — no mocks.

1. EXIT pipeline: LifecycleHandlers.handle_exit -> InMemoryEventBus
   -> LifecycleListeners.on_user_disconnected -> InMemoryPacketQueue
2. HandlerGroup + PacketDispatcher: register_all -> dispatch
3. ListenerGroup + EventBus: register_all -> fire
"""

from __future__ import annotations

import struct

from osu_server.domain.events.base import Event
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.users.events import UserDisconnected
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.services.online_users import OnlineUsersService
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.bancho.protocol.enums import ClientPacketID, ServerPacketID

# ── Constants ───────────────────────────────────────────────────────

_HEADER_FMT = struct.Struct("<HBI")
_INT32_FMT = struct.Struct("<i")
_PACKET_QUEUE_TTL = 300


def _make_session_data(user_id: int) -> SessionData:
    """Create minimal SessionData for testing."""
    return SessionData(
        user_id=user_id,
        username=f"user_{user_id}",
        privileges=0,
        country="JP",
        osu_version="20231111",
        utc_offset=9,
        display_city=False,
        client_hashes="",
        pm_private=False,
    )


def _parse_s2c_header(data: bytes) -> tuple[int, int]:
    """Parse S2C header -> (packet_id, payload_size). Skip compression byte."""
    unpacked: tuple[int, bool, int] = _HEADER_FMT.unpack_from(data)
    packet_id, _, size = unpacked
    return packet_id, size


# ═══════════════════════════════════════════════════════════════════
# Test 1: EXIT Pipeline Integration
# ═══════════════════════════════════════════════════════════════════


class TestExitPipelineIntegration:
    """EXIT handler -> EventBus -> Listener -> PacketQueue (Req 9.2)."""

    async def test_exit_broadcasts_user_quit_to_other_users(self) -> None:
        """When user 1 exits, user 2 and user 3 receive USER_QUIT packets
        with user 1's ID. User 1's queue receives nothing."""
        # Arrange: wire real components
        session_store = InMemorySessionStore()
        event_bus = InMemoryEventBus()
        packet_queue = InMemoryPacketQueue()
        online_users = OnlineUsersService(session_store)

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        listeners = LifecycleListeners(
            online_users=online_users,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        # Create 3 sessions and activate their packet queues
        for uid in (1, 2, 3):
            await session_store.create(uid, f"token_{uid}", _make_session_data(uid))
            await packet_queue.refresh_ttl(uid, _PACKET_QUEUE_TTL)

        # Act: user 1 exits
        await handlers.handle_exit(b"", user_id=1)

        # Assert: user 2 and user 3 have USER_QUIT(user_id=1)
        for uid in (2, 3):
            data = await packet_queue.dequeue_all(uid)
            assert len(data) > 0, f"user {uid} should have received USER_QUIT"

            packet_id, payload_size = _parse_s2c_header(data)
            assert packet_id == ServerPacketID.USER_QUIT
            assert payload_size == 4

            payload = data[_HEADER_FMT.size :]
            quit_user_id: int = _INT32_FMT.unpack(payload)[0]  # pyright: ignore[reportAny]
            assert quit_user_id == 1

        # User 1 should NOT receive their own USER_QUIT
        user1_data = await packet_queue.dequeue_all(1)
        assert user1_data == b""

    async def test_exit_deletes_session(self) -> None:
        """EXIT handler deletes the disconnecting user's session."""
        session_store = InMemorySessionStore()
        event_bus = InMemoryEventBus()
        packet_queue = InMemoryPacketQueue()
        online_users = OnlineUsersService(session_store)

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        listeners = LifecycleListeners(
            online_users=online_users,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        await session_store.create(1, "token_1", _make_session_data(1))
        await packet_queue.refresh_ttl(1, _PACKET_QUEUE_TTL)

        await handlers.handle_exit(b"", user_id=1)

        # Session should be deleted
        assert await session_store.get_by_user(1) is None

    async def test_exit_user_excluded_from_online_list_after_disconnect(self) -> None:
        """After EXIT, the disconnected user no longer appears in online users."""
        session_store = InMemorySessionStore()
        event_bus = InMemoryEventBus()
        packet_queue = InMemoryPacketQueue()
        online_users = OnlineUsersService(session_store)

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        listeners = LifecycleListeners(
            online_users=online_users,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        for uid in (10, 20):
            await session_store.create(uid, f"token_{uid}", _make_session_data(uid))
            await packet_queue.refresh_ttl(uid, _PACKET_QUEUE_TTL)

        await handlers.handle_exit(b"", user_id=10)

        # user 10 is gone
        all_ids = await online_users.get_all_user_ids()
        assert 10 not in all_ids
        assert 20 in all_ids


# ═══════════════════════════════════════════════════════════════════
# Test 2: HandlerGroup + PacketDispatcher Integration
# ═══════════════════════════════════════════════════════════════════


class TestHandlerGroupDispatcherIntegration:
    """register_all wires handlers so PacketDispatcher.dispatch calls them."""

    async def test_dispatch_calls_registered_handler(self) -> None:
        """After register_all, dispatching PONG and EXIT calls the correct handlers."""
        session_store = InMemorySessionStore()
        event_bus = InMemoryEventBus()
        dispatcher = PacketDispatcher()

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        handlers.register_all(dispatcher)

        # Create a session so EXIT has something to delete
        await session_store.create(42, "token_42", _make_session_data(42))

        # Dispatch PONG — should not raise
        await dispatcher.dispatch(ClientPacketID.PONG, b"", user_id=42)

        # Dispatch EXIT — should delete session and fire event
        await dispatcher.dispatch(ClientPacketID.EXIT, b"", user_id=42)

        assert await session_store.get_by_user(42) is None

    async def test_unregistered_packet_is_ignored(self) -> None:
        """Dispatching a packet with no registered handler does not raise."""
        session_store = InMemorySessionStore()
        event_bus = InMemoryEventBus()
        dispatcher = PacketDispatcher()

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        handlers.register_all(dispatcher)

        # SEND_MESSAGE has no handler — should be silently ignored
        await dispatcher.dispatch(ClientPacketID.SEND_MESSAGE, b"\x00", user_id=1)

    async def test_all_lifecycle_handlers_registered(self) -> None:
        """register_all registers exactly PONG and EXIT."""
        session_store = InMemorySessionStore()
        event_bus = InMemoryEventBus()
        dispatcher = PacketDispatcher()

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        handlers.register_all(dispatcher)

        registered = dispatcher.get_handlers()
        assert ClientPacketID.PONG in registered
        assert ClientPacketID.EXIT in registered
        assert len(registered) == ClientPacketID.EXIT.value


# ═══════════════════════════════════════════════════════════════════
# Test 3: ListenerGroup + EventBus Integration
# ═══════════════════════════════════════════════════════════════════


class TestListenerGroupEventBusIntegration:
    """register_all wires listeners so EventBus.fire calls them."""

    async def test_fire_calls_registered_listener(self) -> None:
        """After register_all, firing UserDisconnected triggers the listener."""
        session_store = InMemorySessionStore()
        packet_queue = InMemoryPacketQueue()
        event_bus = InMemoryEventBus()
        online_users = OnlineUsersService(session_store)

        listeners = LifecycleListeners(
            online_users=online_users,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        # Set up an online user who should receive the broadcast
        await session_store.create(5, "token_5", _make_session_data(5))
        await packet_queue.refresh_ttl(5, _PACKET_QUEUE_TTL)

        # Fire event for user 99 disconnecting
        await event_bus.fire(UserDisconnected(user_id=99))

        # User 5 should have received USER_QUIT for user 99
        data = await packet_queue.dequeue_all(5)
        assert len(data) > 0

        packet_id, _ = _parse_s2c_header(data)
        assert packet_id == ServerPacketID.USER_QUIT

        payload = data[_HEADER_FMT.size :]
        quit_user_id: int = _INT32_FMT.unpack(payload)[0]  # pyright: ignore[reportAny]
        assert quit_user_id == 99

    async def test_unsubscribed_event_type_is_ignored(self) -> None:
        """Firing an event type with no listener does not raise."""
        event_bus = InMemoryEventBus()

        # No listeners registered — fire should be a no-op
        await event_bus.fire(UserDisconnected(user_id=1))

    async def test_listener_not_triggered_by_wrong_event_type(self) -> None:
        """LifecycleListeners only responds to UserDisconnected, not others."""
        session_store = InMemorySessionStore()
        packet_queue = InMemoryPacketQueue()
        event_bus = InMemoryEventBus()
        online_users = OnlineUsersService(session_store)

        listeners = LifecycleListeners(
            online_users=online_users,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        await session_store.create(5, "token_5", _make_session_data(5))
        await packet_queue.refresh_ttl(5, _PACKET_QUEUE_TTL)

        # Fire an unrelated event type (just a bare Event)
        await event_bus.fire(Event())

        # User 5 should have no packets
        data = await packet_queue.dequeue_all(5)
        assert data == b""

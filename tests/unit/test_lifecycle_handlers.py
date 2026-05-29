"""Tests for LifecycleHandlers (PONG + EXIT).

Validates:
- Req 5.1: PONG packet accepted without error
- Req 5.2: PONG is in QUIET_C2S_PACKETS (DEBUG-level logging)
- Req 6.1: EXIT calls SessionStore.delete_by_user
- Req 6.2: EXIT fires UserDisconnected event via EventBus
- Req 6.4: EXIT handled without error (logging tested at dispatch level)
- Req 6.5: Idempotent — second EXIT on same user_id causes no error
- Req 6.6: Session deletion guaranteed even when EventBus.fire raises
- Req 9.1: Unit tests with dependency mocks
"""

from __future__ import annotations

import typing

import pytest

from osu_server.domain.users.events import UserDisconnected
from osu_server.infrastructure.messaging.interfaces import EventBus  # noqa: TC001
from osu_server.repositories.interfaces.session_store import SessionStore  # noqa: TC001
from osu_server.transports.bancho.dispatch import QUIET_C2S_PACKETS
from osu_server.transports.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.bancho.protocol.enums import ClientPacketID


class FakeSessionStore:
    def __init__(self) -> None:
        self.deleted_users: list[int] = []

    async def delete_by_user(self, user_id: int) -> None:
        self.deleted_users.append(user_id)


class FakeEventBus:
    def __init__(self) -> None:
        self.fired_events: list[object] = []
        self.raise_on_fire: Exception | None = None

    async def fire(self, event: object) -> None:
        if self.raise_on_fire:
            raise self.raise_on_fire
        self.fired_events.append(event)


@pytest.fixture
def session_store() -> FakeSessionStore:
    """Fake SessionStore."""
    return FakeSessionStore()


@pytest.fixture
def event_bus() -> FakeEventBus:
    """Fake EventBus."""
    return FakeEventBus()


@pytest.fixture
def handlers(session_store: FakeSessionStore, event_bus: FakeEventBus) -> LifecycleHandlers:
    """LifecycleHandlers instance with faked dependencies."""
    return LifecycleHandlers(
        session_store=typing.cast("SessionStore", typing.cast("typing.Any", session_store)),
        event_bus=typing.cast("EventBus", typing.cast("typing.Any", event_bus)),
    )


class TestHandlePong:
    """Req 5.1, 5.2: PONG packet handling."""

    async def test_handle_pong_completes_without_error(self, handlers: LifecycleHandlers) -> None:
        """PONG handler accepts payload and user_id without raising."""
        await handlers.handle_pong(b"", 1)

    async def test_handle_pong_completes_with_arbitrary_payload(
        self, handlers: LifecycleHandlers
    ) -> None:
        """PONG handler ignores payload content."""
        await handlers.handle_pong(b"\xff" * 64, 999)

    def test_pong_is_in_quiet_packets(self) -> None:
        """ClientPacketID.PONG is in QUIET_C2S_PACKETS for DEBUG-level logging."""
        assert ClientPacketID.PONG in QUIET_C2S_PACKETS


class TestHandleExit:
    """Req 6.1, 6.2, 6.4: EXIT packet handling."""

    async def test_exit_fires_user_disconnected_event(
        self, handlers: LifecycleHandlers, event_bus: FakeEventBus
    ) -> None:
        """EXIT fires UserDisconnected with the correct user_id."""
        await handlers.handle_exit(b"", user_id=42)

        assert len(event_bus.fired_events) == 1
        event = event_bus.fired_events[0]
        assert isinstance(event, UserDisconnected)
        assert event.user_id == 42

    async def test_exit_deletes_session(
        self,
        handlers: LifecycleHandlers,
        session_store: FakeSessionStore,
    ) -> None:
        """EXIT calls SessionStore.delete_by_user with the correct user_id."""
        await handlers.handle_exit(b"", user_id=42)

        assert session_store.deleted_users == [42]


class TestHandleExitTryFinally:
    """Req 6.6: Session deletion guaranteed even when EventBus.fire raises."""

    async def test_session_deleted_when_event_fire_raises(
        self,
        session_store: FakeSessionStore,
        event_bus: FakeEventBus,
    ) -> None:
        """delete_by_user is called even if EventBus.fire raises an exception."""
        event_bus.raise_on_fire = RuntimeError("event bus failure")
        handler = LifecycleHandlers(
            session_store=typing.cast("SessionStore", typing.cast("typing.Any", session_store)),
            event_bus=typing.cast("EventBus", typing.cast("typing.Any", event_bus)),
        )

        with pytest.raises(RuntimeError, match="event bus failure"):
            await handler.handle_exit(b"", user_id=7)

        assert session_store.deleted_users == [7]


class TestHandleExitIdempotency:
    """Req 6.5: Second EXIT on same user_id causes no error."""

    async def test_double_exit_no_error(
        self, handlers: LifecycleHandlers, session_store: FakeSessionStore
    ) -> None:
        """Calling handle_exit twice for the same user_id does not raise."""
        await handlers.handle_exit(b"", user_id=10)
        await handlers.handle_exit(b"", user_id=10)

        assert session_store.deleted_users == [10, 10]

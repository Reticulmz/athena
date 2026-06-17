"""Tests for LifecycleHandlers (PONG + EXIT).

Validates:
- Req 5.1: PONG packet accepted without error
- Req 5.2: PONG is in QUIET_C2S_PACKETS (DEBUG-level logging)
- Req 6.1: EXIT calls SessionStore.delete_by_user
- Req 6.2: EXIT fires UserDisconnected event via LocalEventBus
- Req 6.4: EXIT handled without error (logging tested at dispatch level)
- Req 6.5: Idempotent — second EXIT on same user_id causes no error
- Req 6.6: Session deletion guaranteed even when LocalEventBus.fire raises
- Req 9.1: Unit tests with dependency mocks
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import pytest

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.dispatch import QUIET_C2S_PACKETS
from osu_server.transports.stable.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from osu_server.domain.identity.sessions import SessionAuthorization, SessionData

TEvent = TypeVar("TEvent", bound=object)


class FakeSessionStore:
    def __init__(self) -> None:
        self.deleted_users: list[int] = []

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        _ = (user_id, token, data)
        raise NotImplementedError

    async def get(self, token: str) -> SessionData | None:
        _ = token
        raise NotImplementedError

    async def get_by_user(self, user_id: int) -> SessionData | None:
        _ = user_id
        raise NotImplementedError

    async def delete(self, token: str) -> None:
        _ = token
        raise NotImplementedError

    async def exists(self, token: str) -> bool:
        _ = token
        raise NotImplementedError

    async def refresh(self, token: str) -> bool:
        _ = token
        raise NotImplementedError

    async def delete_by_user(self, user_id: int) -> None:
        self.deleted_users.append(user_id)

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        _ = (user_id, authorization)
        raise NotImplementedError

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        _ = (user_id, enabled)
        raise NotImplementedError

    async def list_active_sessions(self) -> list[SessionData]:
        raise NotImplementedError


class FakeLocalEventBus:
    def __init__(self) -> None:
        self.fired_events: list[object] = []
        self.raise_on_fire: Exception | None = None

    async def fire(self, event: object) -> None:
        if self.raise_on_fire:
            raise self.raise_on_fire
        self.fired_events.append(event)

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], Awaitable[None]],
    ) -> None:
        _ = (event_type, handler)
        raise NotImplementedError


@pytest.fixture
def session_store() -> FakeSessionStore:
    """Fake SessionStore."""
    return FakeSessionStore()


@pytest.fixture
def event_bus() -> FakeLocalEventBus:
    """Fake LocalEventBus."""
    return FakeLocalEventBus()


@pytest.fixture
def handlers(session_store: FakeSessionStore, event_bus: FakeLocalEventBus) -> LifecycleHandlers:
    """LifecycleHandlers instance with faked dependencies."""
    return LifecycleHandlers(
        session_store=session_store,
        event_bus=event_bus,
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
        self, handlers: LifecycleHandlers, event_bus: FakeLocalEventBus
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
    """Req 6.6: Session deletion guaranteed even when LocalEventBus.fire raises."""

    async def test_session_deleted_when_event_fire_raises(
        self,
        session_store: FakeSessionStore,
        event_bus: FakeLocalEventBus,
    ) -> None:
        """delete_by_user is called even if LocalEventBus.fire raises an exception."""
        event_bus.raise_on_fire = RuntimeError("event bus failure")
        handler = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
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

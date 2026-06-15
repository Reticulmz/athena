"""Tests for ListenerGroup base class.

Validates:
- Req 3.1: ListenerGroup extends RouteGroup with `listens = route` alias
- Req 3.2: register_all(event_bus) subscribes all @listens methods
- Req 3.3: ListenerGroup registration pattern is symmetric with HandlerGroup
- Req 1.5: register_all warns when 0 listeners registered
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

import structlog
import structlog.testing

from osu_server.infrastructure.messaging.memory import InMemoryLocalEventBus
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup
from osu_server.transports.stable.bancho.listeners.base import ListenerGroup, listens
from osu_server.transports.stable.bancho.routing import RouteGroup, route


@dataclass(frozen=True, slots=True)
class FakeEvent:
    """Fake event for testing."""

    value: int


@dataclass(frozen=True, slots=True)
class AnotherEvent:
    """Another fake event for testing."""

    data: str


class TestListenerGroupIsRouteGroup:
    """Req 3.1: ListenerGroup extends RouteGroup."""

    def test_listener_group_is_subclass_of_route_group(self) -> None:
        assert issubclass(ListenerGroup, RouteGroup)

    def test_listens_is_route_alias(self) -> None:
        """listens should be the same function as route."""
        assert listens is route


class TestRegisterAll:
    """Req 3.2: register_all subscribes all @listens methods with event_bus."""

    async def test_register_all_subscribes_listeners(self) -> None:
        """After register_all, firing an event calls the subscribed listener."""
        received: list[FakeEvent] = []

        class MyListeners(ListenerGroup):
            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                received.append(event)

        event_bus = InMemoryLocalEventBus()
        group = MyListeners()
        group.register_all(event_bus)

        event = FakeEvent(value=42)
        await event_bus.fire(event)

        assert len(received) == 1
        assert received[0] is event

    async def test_register_all_subscribes_multiple_listeners(self) -> None:
        """All @listens methods are subscribed."""
        fake_received: list[FakeEvent] = []
        another_received: list[AnotherEvent] = []

        class MyListeners(ListenerGroup):
            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                fake_received.append(event)

            @listens(AnotherEvent)
            async def on_another(self, event: AnotherEvent) -> None:
                another_received.append(event)

        event_bus = InMemoryLocalEventBus()
        group = MyListeners()
        group.register_all(event_bus)

        await event_bus.fire(FakeEvent(value=1))
        await event_bus.fire(AnotherEvent(data="hello"))

        assert len(fake_received) == 1
        assert len(another_received) == 1

    async def test_registered_listener_is_bound_method(self) -> None:
        """Listener receives events through the bound method with correct self."""
        results: list[int] = []

        @final
        class MyListeners(ListenerGroup):
            def __init__(self, multiplier: int) -> None:
                self.multiplier = multiplier

            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                results.append(event.value * self.multiplier)

        event_bus = InMemoryLocalEventBus()
        group = MyListeners(multiplier=10)
        group.register_all(event_bus)

        await event_bus.fire(FakeEvent(value=3))
        assert results == [30]


class TestRegisterAllLogging:
    """Req 3.2 (logging): register_all logs count; Req 1.5: warns on 0."""

    def test_register_all_logs_listeners_registered(self) -> None:
        """Successful registration emits 'listeners_registered' log."""

        class MyListeners(ListenerGroup):
            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                _ = event

        event_bus = InMemoryLocalEventBus()
        group = MyListeners()

        with structlog.testing.capture_logs() as logs:
            group.register_all(event_bus)

        reg_logs = [entry for entry in logs if entry.get("event") == "listeners_registered"]
        assert len(reg_logs) == 1
        assert reg_logs[0]["group"] == "MyListeners"
        assert reg_logs[0]["count"] == 1

    def test_register_all_logs_correct_count(self) -> None:
        """Log entry count matches the number of registered listeners."""

        class MultiListeners(ListenerGroup):
            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                _ = event

            @listens(AnotherEvent)
            async def on_another(self, event: AnotherEvent) -> None:
                _ = event

        event_bus = InMemoryLocalEventBus()
        group = MultiListeners()

        with structlog.testing.capture_logs() as logs:
            group.register_all(event_bus)

        reg_logs = [entry for entry in logs if entry.get("event") == "listeners_registered"]
        assert reg_logs[0]["count"] == 2

    def test_register_all_warns_on_empty_group(self) -> None:
        """Empty group (0 listeners) emits a warning log."""

        class EmptyListeners(ListenerGroup):
            pass

        event_bus = InMemoryLocalEventBus()
        group = EmptyListeners()

        with structlog.testing.capture_logs() as logs:
            group.register_all(event_bus)

        warn_logs = [entry for entry in logs if entry.get("log_level") == "warning"]
        assert len(warn_logs) == 1
        assert warn_logs[0]["group"] == "EmptyListeners"


class TestSymmetryWithHandlerGroup:
    """Req 3.3: ListenerGroup pattern is symmetric with HandlerGroup."""

    def test_both_extend_route_group(self) -> None:
        """Both HandlerGroup and ListenerGroup extend RouteGroup."""
        assert issubclass(HandlerGroup, RouteGroup)
        assert issubclass(ListenerGroup, RouteGroup)

    def test_both_have_register_all(self) -> None:
        """Both classes expose a register_all method."""
        assert hasattr(HandlerGroup, "register_all")
        assert hasattr(ListenerGroup, "register_all")

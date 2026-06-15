"""Tests for local event fanout."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.messaging.memory import InMemoryLocalEventBus


@dataclass(slots=True)
class _UserLoggedIn:
    user_id: int


@dataclass(slots=True)
class _ChatMessageSent:
    sender_id: int
    text: str


@pytest.fixture
def bus() -> InMemoryLocalEventBus:
    return InMemoryLocalEventBus()


class TestProtocolCompliance:
    def test_is_local_event_bus(self, bus: InMemoryLocalEventBus) -> None:
        assert isinstance(bus, LocalEventBus)


class TestFireAndSubscribe:
    async def test_handler_receives_event(self, bus: InMemoryLocalEventBus) -> None:
        received: list[_UserLoggedIn] = []

        async def on_login(event: _UserLoggedIn) -> None:
            received.append(event)

        bus.subscribe(_UserLoggedIn, on_login)
        await bus.fire(_UserLoggedIn(user_id=1))

        assert len(received) == 1
        assert received[0].user_id == 1

    async def test_fire_without_subscribers_is_noop(self, bus: InMemoryLocalEventBus) -> None:
        await bus.fire(_UserLoggedIn(user_id=1))

    async def test_handler_only_receives_subscribed_type(
        self,
        bus: InMemoryLocalEventBus,
    ) -> None:
        received: list[object] = []

        async def on_login(event: _UserLoggedIn) -> None:
            received.append(event)

        bus.subscribe(_UserLoggedIn, on_login)
        await bus.fire(_ChatMessageSent(sender_id=1, text="hello"))

        assert len(received) == 0


class TestMultipleHandlers:
    async def test_multiple_handlers_called_in_order(self, bus: InMemoryLocalEventBus) -> None:
        order: list[str] = []

        async def first(_event: _UserLoggedIn) -> None:
            order.append("first")

        async def second(_event: _UserLoggedIn) -> None:
            order.append("second")

        async def third(_event: _UserLoggedIn) -> None:
            order.append("third")

        bus.subscribe(_UserLoggedIn, first)
        bus.subscribe(_UserLoggedIn, second)
        bus.subscribe(_UserLoggedIn, third)

        await bus.fire(_UserLoggedIn(user_id=1))

        assert order == ["first", "second", "third"]

    async def test_multiple_event_types(self, bus: InMemoryLocalEventBus) -> None:
        logins: list[_UserLoggedIn] = []
        chats: list[_ChatMessageSent] = []

        async def on_login(event: _UserLoggedIn) -> None:
            logins.append(event)

        async def on_chat(event: _ChatMessageSent) -> None:
            chats.append(event)

        bus.subscribe(_UserLoggedIn, on_login)
        bus.subscribe(_ChatMessageSent, on_chat)

        await bus.fire(_UserLoggedIn(user_id=1))
        await bus.fire(_ChatMessageSent(sender_id=2, text="hi"))

        assert len(logins) == 1
        assert len(chats) == 1


class TestExceptionIsolation:
    async def test_handler_exception_does_not_stop_others(
        self,
        bus: InMemoryLocalEventBus,
    ) -> None:
        results: list[str] = []

        async def failing(_event: _UserLoggedIn) -> None:
            msg = "handler error"
            raise RuntimeError(msg)

        async def succeeding(_event: _UserLoggedIn) -> None:
            results.append("ok")

        bus.subscribe(_UserLoggedIn, failing)
        bus.subscribe(_UserLoggedIn, succeeding)

        await bus.fire(_UserLoggedIn(user_id=1))

        assert results == ["ok"]

    async def test_handler_exception_is_logged(
        self,
        bus: InMemoryLocalEventBus,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        async def failing(_event: _UserLoggedIn) -> None:
            msg = "boom"
            raise ValueError(msg)

        bus.subscribe(_UserLoggedIn, failing)

        with caplog.at_level("ERROR"):
            await bus.fire(_UserLoggedIn(user_id=1))

        assert any("failing" in record.message for record in caplog.records)
        assert any(record.exc_info is not None for record in caplog.records)


class TestLocalOnlyContract:
    def test_contract_names_local_scope(self) -> None:
        assert LocalEventBus.__name__ == "LocalEventBus"
        assert "cross-replica" in (LocalEventBus.__doc__ or "")

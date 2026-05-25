"""Tests for HandlerGroup base class.

Validates:
- Req 2.1: HandlerGroup extends RouteGroup with `handles = route` alias
- Req 2.2: register_all(dispatcher) registers @handles methods
- Req 2.3: register_all logs "handlers_registered" with group name and count
- Req 1.5: register_all warns when 0 handlers registered
- Req 2.4: Duplicate packet ID registration raises DuplicateHandlerError
"""

from __future__ import annotations

import pytest
import structlog
import structlog.testing

from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.errors import DuplicateHandlerError
from osu_server.transports.bancho.routing import RouteGroup, route


class TestHandlerGroupIsRouteGroup:
    """Req 2.1: HandlerGroup extends RouteGroup."""

    def test_handler_group_is_subclass_of_route_group(self) -> None:
        assert issubclass(HandlerGroup, RouteGroup)

    def test_handles_is_route_alias(self) -> None:
        """handles should be the same function as route."""
        assert handles is route


class TestRegisterAll:
    """Req 2.2: register_all registers all @handles methods with dispatcher."""

    def test_register_all_registers_handlers(self) -> None:
        """After register_all, dispatcher should contain all declared handlers."""

        class MyHandlers(HandlerGroup):
            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                pass

        dispatcher = PacketDispatcher()
        group = MyHandlers()
        group.register_all(dispatcher)

        registered = dispatcher.get_handlers()
        assert ClientPacketID.PONG in registered

    def test_register_all_registers_multiple_handlers(self) -> None:
        """All @handles methods are registered."""

        class MyHandlers(HandlerGroup):
            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                pass

            @handles(ClientPacketID.EXIT)
            async def handle_exit(self, payload: bytes, user_id: int) -> None:
                pass

        dispatcher = PacketDispatcher()
        group = MyHandlers()
        group.register_all(dispatcher)

        registered = dispatcher.get_handlers()
        assert ClientPacketID.PONG in registered
        assert ClientPacketID.EXIT in registered

    async def test_registered_handler_is_bound_method(self) -> None:
        """Registered handler should be the bound method of the group instance."""
        called_with: list[tuple[bytes, int]] = []

        class MyHandlers(HandlerGroup):
            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                called_with.append((payload, user_id))

        dispatcher = PacketDispatcher()
        group = MyHandlers()
        group.register_all(dispatcher)

        await dispatcher.dispatch(ClientPacketID.PONG, b"\x00", 42)
        assert len(called_with) == 1
        assert called_with[0] == (b"\x00", 42)


class TestRegisterAllLogging:
    """Req 2.3: register_all logs registration count; Req 1.5: warns on 0."""

    def test_register_all_logs_handlers_registered(self) -> None:
        """Successful registration emits 'handlers_registered' log."""

        class MyHandlers(HandlerGroup):
            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                pass

        dispatcher = PacketDispatcher()
        group = MyHandlers()

        with structlog.testing.capture_logs() as logs:
            group.register_all(dispatcher)

        reg_logs = [entry for entry in logs if entry.get("event") == "handlers_registered"]
        assert len(reg_logs) == 1
        assert reg_logs[0]["group"] == "MyHandlers"
        assert reg_logs[0]["count"] == 1

    def test_register_all_logs_correct_count(self) -> None:
        """Log entry count matches the number of registered handlers."""

        class MultiHandlers(HandlerGroup):
            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                pass

            @handles(ClientPacketID.EXIT)
            async def handle_exit(self, payload: bytes, user_id: int) -> None:
                pass

        dispatcher = PacketDispatcher()
        group = MultiHandlers()

        with structlog.testing.capture_logs() as logs:
            group.register_all(dispatcher)

        reg_logs = [entry for entry in logs if entry.get("event") == "handlers_registered"]
        assert reg_logs[0]["count"] == 2  # noqa: PLR2004

    def test_register_all_warns_on_empty_group(self) -> None:
        """Empty group (0 handlers) emits a warning log."""

        class EmptyHandlers(HandlerGroup):
            pass

        dispatcher = PacketDispatcher()
        group = EmptyHandlers()

        with structlog.testing.capture_logs() as logs:
            group.register_all(dispatcher)

        warn_logs = [entry for entry in logs if entry.get("log_level") == "warning"]
        assert len(warn_logs) == 1
        assert warn_logs[0]["group"] == "EmptyHandlers"


class TestDuplicateHandlerError:
    """Req 2.4: Duplicate packet ID raises DuplicateHandlerError."""

    def test_duplicate_packet_id_raises(self) -> None:
        """Registering two groups with the same packet ID raises error."""

        class GroupA(HandlerGroup):
            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                pass

        class GroupB(HandlerGroup):
            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                pass

        dispatcher = PacketDispatcher()
        group_a = GroupA()
        group_a.register_all(dispatcher)

        group_b = GroupB()
        with pytest.raises(DuplicateHandlerError):
            group_b.register_all(dispatcher)

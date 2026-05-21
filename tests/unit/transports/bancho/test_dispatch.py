# ruff: noqa: PLR2004
"""Tests for PacketDispatcher.

Validates:
- Req 5.1: Decorator-based handler registration by ClientPacketID
- Req 5.2: Dispatch calls registered handler for matching ClientPacketID
- Req 5.3: Dispatch ignores unregistered ClientPacketID (no error)
- Req 5.4: get_handlers returns read-only copy of all registered handlers
- Req 5.5: Duplicate registration raises DuplicateHandlerError
"""

import pytest

from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.protocol.enums import ClientPacketID
from osu_server.transports.bancho.protocol.errors import DuplicateHandlerError


class TestRegister:
    """Req 5.1: Decorator registers handler for a ClientPacketID."""

    def test_register_returns_decorator(self) -> None:
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler(payload: bytes) -> None:
            pass

        assert ClientPacketID.PONG in dp.get_handlers()

    def test_register_preserves_function(self) -> None:
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.EXIT)
        async def my_handler(payload: bytes) -> None:
            pass

        assert dp.get_handlers()[ClientPacketID.EXIT] is my_handler

    def test_register_multiple_different_ids(self) -> None:
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler_a(payload: bytes) -> None:
            pass

        @dp.register(ClientPacketID.EXIT)
        async def handler_b(payload: bytes) -> None:
            pass

        handlers = dp.get_handlers()
        assert len(handlers) == 2
        assert ClientPacketID.PONG in handlers
        assert ClientPacketID.EXIT in handlers


class TestDispatch:
    """Req 5.2: Dispatch calls registered handler."""

    @pytest.mark.asyncio
    async def test_dispatch_calls_handler(self) -> None:
        dp = PacketDispatcher()
        called_with: list[bytes] = []

        @dp.register(ClientPacketID.PONG)
        async def handler(payload: bytes) -> None:
            called_with.append(payload)

        await dp.dispatch(ClientPacketID.PONG, b"\x01\x02")
        assert called_with == [b"\x01\x02"]

    @pytest.mark.asyncio
    async def test_dispatch_correct_handler_for_id(self) -> None:
        dp = PacketDispatcher()
        results: list[str] = []

        @dp.register(ClientPacketID.PONG)
        async def pong_handler(_payload: bytes) -> None:
            results.append("pong")

        @dp.register(ClientPacketID.EXIT)
        async def exit_handler(_payload: bytes) -> None:
            results.append("exit")

        await dp.dispatch(ClientPacketID.EXIT, b"")
        assert results == ["exit"]


class TestDispatchUnregistered:
    """Req 5.3: Unregistered ClientPacketID is silently ignored."""

    @pytest.mark.asyncio
    async def test_unregistered_id_no_error(self) -> None:
        dp = PacketDispatcher()
        # Should not raise
        await dp.dispatch(ClientPacketID.PONG, b"")

    @pytest.mark.asyncio
    async def test_unregistered_id_no_side_effects(self) -> None:
        dp = PacketDispatcher()
        called = False

        @dp.register(ClientPacketID.EXIT)
        async def handler(_payload: bytes) -> None:
            nonlocal called
            called = True

        await dp.dispatch(ClientPacketID.PONG, b"")
        assert not called


class TestGetHandlers:
    """Req 5.4: get_handlers returns read-only copy."""

    def test_returns_dict(self) -> None:
        dp = PacketDispatcher()
        assert isinstance(dp.get_handlers(), dict)

    def test_returns_copy(self) -> None:
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler(payload: bytes) -> None:
            pass

        handlers = dp.get_handlers()
        handlers.clear()
        # Original should be unaffected
        assert len(dp.get_handlers()) == 1

    def test_empty_when_no_registrations(self) -> None:
        dp = PacketDispatcher()
        assert dp.get_handlers() == {}


class TestDuplicateRegistration:
    """Req 5.5: Duplicate registration raises DuplicateHandlerError."""

    def test_duplicate_raises(self) -> None:
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler_a(payload: bytes) -> None:
            pass

        with pytest.raises(DuplicateHandlerError):

            @dp.register(ClientPacketID.PONG)
            async def handler_b(payload: bytes) -> None:
                pass

    def test_duplicate_error_message_contains_id(self) -> None:
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler_a(payload: bytes) -> None:
            pass

        with pytest.raises(DuplicateHandlerError, match="PONG"):

            @dp.register(ClientPacketID.PONG)
            async def handler_b(payload: bytes) -> None:
                pass

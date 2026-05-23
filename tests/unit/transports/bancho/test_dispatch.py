# ruff: noqa: PLR2004
"""Tests for PacketDispatcher.

Validates:
- Req 5.1: Decorator-based handler registration by ClientPacketID
- Req 5.2: Dispatch calls registered handler for matching ClientPacketID
- Req 5.3: Dispatch ignores unregistered ClientPacketID (no error)
- Req 5.4: get_handlers returns read-only copy of all registered handlers
- Req 5.5: Duplicate registration raises DuplicateHandlerError
- Logging Req 5.1: C2S packet logging with packet name and payload size
- Logging Req 5.2: Normal packets logged at INFO with payload
- Logging Req 5.3: Noisy packets logged at DEBUG only
- Logging Req 5.4: Unhandled packets logged at DEBUG
"""

import pytest
import structlog.testing

from osu_server.transports.bancho.dispatch import QUIET_C2S_PACKETS, PacketDispatcher
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

    async def test_dispatch_calls_handler(self) -> None:
        dp = PacketDispatcher()
        called_with: list[bytes] = []

        @dp.register(ClientPacketID.PONG)
        async def handler(payload: bytes) -> None:
            called_with.append(payload)

        await dp.dispatch(ClientPacketID.PONG, b"\x01\x02")
        assert called_with == [b"\x01\x02"]

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

    async def test_unregistered_id_no_error(self) -> None:
        dp = PacketDispatcher()
        # Should not raise
        await dp.dispatch(ClientPacketID.PONG, b"")

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


class TestQuietC2sPackets:
    """QUIET_C2S_PACKETS definition validation."""

    def test_contains_pong(self) -> None:
        assert ClientPacketID.PONG in QUIET_C2S_PACKETS

    def test_contains_stats_request(self) -> None:
        assert ClientPacketID.STATS_REQUEST in QUIET_C2S_PACKETS

    def test_contains_presence_request(self) -> None:
        assert ClientPacketID.PRESENCE_REQUEST in QUIET_C2S_PACKETS

    def test_is_frozenset(self) -> None:
        assert isinstance(QUIET_C2S_PACKETS, frozenset)


class TestDispatchLogging:
    """Logging Req 5.1-5.4: C2S packet dispatch logging."""

    async def test_normal_packet_logged_at_info(self) -> None:
        """Req 5.1, 5.2: Normal (non-quiet) packet logged at INFO with name and size."""
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.SEND_MESSAGE)
        async def handler(payload: bytes) -> None:
            pass

        payload = b"\x01\x02\x03"
        with structlog.testing.capture_logs() as logs:
            await dp.dispatch(ClientPacketID.SEND_MESSAGE, payload)

        c2s_logs = [log for log in logs if log["event"] == "c2s_packet"]
        assert len(c2s_logs) == 1
        assert c2s_logs[0]["log_level"] == "info"
        assert c2s_logs[0]["packet"] == "SEND_MESSAGE"
        assert c2s_logs[0]["size"] == 3

    async def test_quiet_packet_logged_at_debug(self) -> None:
        """Req 5.3: Noisy (quiet) packet logged at DEBUG only."""
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler(payload: bytes) -> None:
            pass

        with structlog.testing.capture_logs() as logs:
            await dp.dispatch(ClientPacketID.PONG, b"\x00")

        c2s_logs = [log for log in logs if log["event"] == "c2s_packet"]
        assert len(c2s_logs) == 1
        assert c2s_logs[0]["log_level"] == "debug"
        assert c2s_logs[0]["packet"] == "PONG"
        assert c2s_logs[0]["size"] == 1

    async def test_unhandled_packet_logged_at_debug(self) -> None:
        """Req 5.4: Unregistered packet logged at DEBUG as c2s_unhandled."""
        dp = PacketDispatcher()

        with structlog.testing.capture_logs() as logs:
            await dp.dispatch(ClientPacketID.SEND_MESSAGE, b"\xab\xcd")

        unhandled_logs = [log for log in logs if log["event"] == "c2s_unhandled"]
        assert len(unhandled_logs) == 1
        assert unhandled_logs[0]["log_level"] == "debug"
        assert unhandled_logs[0]["packet"] == "SEND_MESSAGE"
        assert unhandled_logs[0]["size"] == 2

    async def test_all_quiet_packets_logged_at_debug(self) -> None:
        """All packets in QUIET_C2S_PACKETS are logged at debug, not info."""
        dp = PacketDispatcher()

        for packet_id in QUIET_C2S_PACKETS:

            @dp.register(packet_id)
            async def handler(payload: bytes) -> None:
                pass

        for packet_id in QUIET_C2S_PACKETS:
            with structlog.testing.capture_logs() as logs:
                await dp.dispatch(packet_id, b"")

            c2s_logs = [log for log in logs if log["event"] == "c2s_packet"]
            assert len(c2s_logs) == 1, f"{packet_id.name} should produce exactly 1 log"
            assert c2s_logs[0]["log_level"] == "debug", (
                f"{packet_id.name} should be logged at debug"
            )

    async def test_dispatch_still_calls_handler_after_logging(self) -> None:
        """Logging must not interfere with handler invocation."""
        dp = PacketDispatcher()
        called_with: list[bytes] = []

        @dp.register(ClientPacketID.EXIT)
        async def handler(payload: bytes) -> None:
            called_with.append(payload)

        with structlog.testing.capture_logs():
            await dp.dispatch(ClientPacketID.EXIT, b"\xff")

        assert called_with == [b"\xff"]

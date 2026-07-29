"""PacketDispatcher の handler registration, dispatch, structured logging を検証する.

decorator registration, packet ID routing, 未登録 packet, snapshot, 重複 registration,
logging level を確認する.
"""

import pytest
import structlog.testing

from osu_server.transports.stable.bancho.dispatch import QUIET_C2S_PACKETS, PacketDispatcher
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import DuplicateHandlerError


class TestRegister:
    """register decorator が ClientPacketID と handler を関連付けることを検証する."""

    def test_register_returns_decorator(self) -> None:
        """Register が handler を registry に追加する decorator を返すことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler(_payload: bytes, _user_id: int) -> None:
            """PONG registration 用の no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler

        assert ClientPacketID.PONG in dp.get_handlers()

    def test_register_preserves_function(self) -> None:
        """Register decorator が元の handler function object を保持することを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.EXIT)
        async def my_handler(_payload: bytes, _user_id: int) -> None:
            """EXIT registration 用の no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = my_handler

        assert dp.get_handlers()[ClientPacketID.EXIT] is my_handler

    def test_register_multiple_different_ids(self) -> None:
        """異なる packet ID の handler を同じ dispatcher に登録できることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler_a(_payload: bytes, _user_id: int) -> None:
            """PONG registration 用の no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler_a

        @dp.register(ClientPacketID.EXIT)
        async def handler_b(_payload: bytes, _user_id: int) -> None:
            """EXIT registration 用の no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler_b

        handlers = dp.get_handlers()
        assert len(handlers) == 2
        assert ClientPacketID.PONG in handlers
        assert ClientPacketID.EXIT in handlers


class TestDispatch:
    """dispatch が packet ID に対応する登録済み handler を呼び出すことを検証する."""

    async def test_dispatch_calls_handler(self) -> None:
        """Dispatch が payload と user ID を登録済み handler に渡すことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()
        called_with: list[tuple[bytes, int]] = []

        @dp.register(ClientPacketID.PONG)
        async def handler(payload: bytes, user_id: int) -> None:
            """呼び出された payload と user ID を test list に記録する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """
            called_with.append((payload, user_id))

        _ = handler

        await dp.dispatch(ClientPacketID.PONG, b"\x01\x02", 1)
        assert called_with == [(b"\x01\x02", 1)]

    async def test_dispatch_correct_handler_for_id(self) -> None:
        """Dispatch が packet ID に対応する handler だけを選択することを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()
        results: list[str] = []

        @dp.register(ClientPacketID.PONG)
        async def pong_handler(_payload: bytes, _user_id: int) -> None:
            """PONG dispatch を result list に記録する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """
            results.append("pong")

        _ = pong_handler

        @dp.register(ClientPacketID.EXIT)
        async def exit_handler(_payload: bytes, _user_id: int) -> None:
            """EXIT dispatch を result list に記録する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """
            results.append("exit")

        _ = exit_handler

        await dp.dispatch(ClientPacketID.EXIT, b"", 1)
        assert results == ["exit"]


class TestDispatchUnregistered:
    """未登録 ClientPacketID を dispatch が副作用なしで無視することを検証する."""

    async def test_unregistered_id_no_error(self) -> None:
        """未登録 packet ID の dispatch が例外を送出しないことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()
        # Should not raise
        await dp.dispatch(ClientPacketID.PONG, b"", 1)

    async def test_unregistered_id_no_side_effects(self) -> None:
        """未登録 packet ID が別の登録済み handler を呼び出さないことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()
        called = False

        @dp.register(ClientPacketID.EXIT)
        async def handler(_payload: bytes, _user_id: int) -> None:
            """呼び出しを boolean flag に記録する EXIT handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """
            nonlocal called
            called = True

        _ = handler

        await dp.dispatch(ClientPacketID.PONG, b"", 1)
        assert not called


class TestGetHandlers:
    """get_handlers が registration state の独立した snapshot を返すことを検証する."""

    def test_returns_dict(self) -> None:
        """get_handlers が dict instance を返すことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()
        assert isinstance(dp.get_handlers(), dict)

    def test_returns_copy(self) -> None:
        """取得した handler dict の mutation が dispatcher registry に影響しないことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler(_payload: bytes, _user_id: int) -> None:
            """PONG registration 用の no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler

        handlers = dp.get_handlers()
        handlers.clear()
        # Original should be unaffected
        assert len(dp.get_handlers()) == 1

    def test_empty_when_no_registrations(self) -> None:
        """Handler 未登録の dispatcher が空 dict snapshot を返すことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()
        assert dp.get_handlers() == {}


class TestDuplicateRegistration:
    """同じ ClientPacketID への重複 handler registration を検証する."""

    def test_duplicate_raises(self) -> None:
        """重複 handler registration が DuplicateHandlerError を送出することを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler_a(_payload: bytes, _user_id: int) -> None:
            """先に登録する PONG no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler_a

        async def handler_b(_payload: bytes, _user_id: int) -> None:
            """重複 registration を試す PONG no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler_b

        with pytest.raises(DuplicateHandlerError):
            _ = dp.register(ClientPacketID.PONG)(handler_b)

    def test_duplicate_error_message_contains_id(self) -> None:
        """重複 registration error message が packet ID 名を含むことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler_a(_payload: bytes, _user_id: int) -> None:
            """先に登録する PONG no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler_a

        async def handler_b(_payload: bytes, _user_id: int) -> None:
            """重複 registration を試す PONG no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler_b

        with pytest.raises(DuplicateHandlerError, match="PONG"):
            _ = dp.register(ClientPacketID.PONG)(handler_b)


class TestQuietC2sPackets:
    """QUIET_C2S_PACKETS の packet member と immutable collection contract を検証する."""

    def test_contains_pong(self) -> None:
        """QUIET_C2S_PACKETS が PONG を含むことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        assert ClientPacketID.PONG in QUIET_C2S_PACKETS

    def test_contains_stats_request(self) -> None:
        """QUIET_C2S_PACKETS が STATS_REQUEST を含むことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        assert ClientPacketID.STATS_REQUEST in QUIET_C2S_PACKETS

    def test_contains_presence_request(self) -> None:
        """QUIET_C2S_PACKETS が PRESENCE_REQUEST を含むことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        assert ClientPacketID.PRESENCE_REQUEST in QUIET_C2S_PACKETS

    def test_contains_presence_request_all(self) -> None:
        """QUIET_C2S_PACKETS が PRESENCE_REQUEST_ALL を含むことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        assert ClientPacketID.PRESENCE_REQUEST_ALL in QUIET_C2S_PACKETS

    def test_is_frozenset(self) -> None:
        """QUIET_C2S_PACKETS が immutable frozenset であることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        assert isinstance(QUIET_C2S_PACKETS, frozenset)


class TestDispatchLogging:
    """C2S packet dispatch 時の structured logging event と level を検証する."""

    async def test_normal_packet_logged_at_info(self) -> None:
        """Quiet ではない packet が名前と size を持つ info event として記録されることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.SEND_MESSAGE)
        async def handler(_payload: bytes, _user_id: int) -> None:
            """SEND_MESSAGE logging 用の no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler

        payload = b"\x01\x02\x03"
        with structlog.testing.capture_logs() as logs:
            await dp.dispatch(ClientPacketID.SEND_MESSAGE, payload, 1)

        c2s_logs = [log for log in logs if log["event"] == "c2s_packet"]
        assert len(c2s_logs) == 1
        assert c2s_logs[0]["log_level"] == "info"
        assert c2s_logs[0]["packet"] == "SEND_MESSAGE"
        assert c2s_logs[0]["size"] == 3

    async def test_quiet_packet_logged_at_debug(self) -> None:
        """Quiet packet が名前と size を持つ debug event として記録されることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        @dp.register(ClientPacketID.PONG)
        async def handler(_payload: bytes, _user_id: int) -> None:
            """PONG logging 用の no-op async handler を定義する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """

        _ = handler

        with structlog.testing.capture_logs() as logs:
            await dp.dispatch(ClientPacketID.PONG, b"\x00", 1)

        c2s_logs = [log for log in logs if log["event"] == "c2s_packet"]
        assert len(c2s_logs) == 1
        assert c2s_logs[0]["log_level"] == "debug"
        assert c2s_logs[0]["packet"] == "PONG"
        assert c2s_logs[0]["size"] == 1

    async def test_unhandled_packet_logged_at_debug(self) -> None:
        """未登録 packet が c2s_unhandled debug event として記録されることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        with structlog.testing.capture_logs() as logs:
            await dp.dispatch(ClientPacketID.SEND_MESSAGE, b"\xab\xcd", 1)

        unhandled_logs = [log for log in logs if log["event"] == "c2s_unhandled"]
        assert len(unhandled_logs) == 1
        assert unhandled_logs[0]["log_level"] == "debug"
        assert unhandled_logs[0]["packet"] == "SEND_MESSAGE"
        assert unhandled_logs[0]["size"] == 2

    async def test_all_quiet_packets_logged_at_debug(self) -> None:
        """QUIET_C2S_PACKETS の全 member が debug event として記録されることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()

        for packet_id in QUIET_C2S_PACKETS:

            @dp.register(packet_id)
            async def handler(_payload: bytes, _user_id: int) -> None:
                """Current quiet packet registration 用の no-op async handler を定義する.

                Returns:
                    None: 処理を完了し, 呼び出し側へ値を返さない.
                """

            _ = handler

        for packet_id in QUIET_C2S_PACKETS:
            with structlog.testing.capture_logs() as logs:
                await dp.dispatch(packet_id, b"", 1)

            c2s_logs = [log for log in logs if log["event"] == "c2s_packet"]
            assert len(c2s_logs) == 1, f"{packet_id.name} should produce exactly 1 log"
            assert c2s_logs[0]["log_level"] == "debug", (
                f"{packet_id.name} should be logged at debug"
            )

    async def test_dispatch_still_calls_handler_after_logging(self) -> None:
        """Logging 後も dispatch が登録済み handler を呼び出すことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        dp = PacketDispatcher()
        called_with: list[tuple[bytes, int]] = []

        @dp.register(ClientPacketID.EXIT)
        async def handler(payload: bytes, user_id: int) -> None:
            """Logging 後の payload と user ID を test list に記録する.

            Returns:
                None: 処理を完了し, 呼び出し側へ値を返さない.
            """
            called_with.append((payload, user_id))

        _ = handler

        with structlog.testing.capture_logs():
            await dp.dispatch(ClientPacketID.EXIT, b"\xff", 42)

        assert called_with == [(b"\xff", 42)]

"""HandlerGroupのrouting登録と重複検出の契約を検証するmodule.

decorator aliasとdispatcher登録およびregistration logのobservable contractを対象にする.
"""

from __future__ import annotations

import pytest
import structlog
import structlog.testing

from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import DuplicateHandlerError
from osu_server.transports.stable.bancho.routing import RouteGroup, route


class TestHandlerGroupIsRouteGroup:
    """HandlerGroupとRouteGroupの継承およびdecorator aliasを検証するtest群."""

    def test_handler_group_is_subclass_of_route_group(self) -> None:
        """HandlerGroupがRouteGroupを継承することを検証する.

        二つのclassをissubclassで比較しrouting共通APIを継承するTrue結果を確認する.

        Returns:
            None: 継承契約の検証を完了する.
        """
        assert issubclass(HandlerGroup, RouteGroup)

    def test_handles_is_route_alias(self) -> None:
        """handlesがrouteと同一のdecorator aliasであることを検証する.

        二つのdecorator functionをidentity比較し同じroute登録規則を使うことを確認する.

        Returns:
            None: decorator alias契約の検証を完了する.
        """
        assert handles is route


class TestRegisterAll:
    """register_allが@handles methodをdispatcherへ登録することを検証するtest群."""

    def test_register_all_registers_handlers(self) -> None:
        """単一の@handles methodがdispatcherへ登録されることを検証する.

        PONG handlerを持つgroupへregister_allを実行しdispatcherのhandler集合にPONGが現れることを
        確認する.

        Returns:
            None: 単一handler登録の検証を完了する.
        """

        class MyHandlers(HandlerGroup):
            """PONG packetを登録するtest用HandlerGroup."""

            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                """PONG packetを受け取る登録専用handler.

                Args:
                    payload (bytes): dispatcherから渡されるpacket payload.
                    user_id (int): packet送信userのID.

                Returns:
                    None: payloadを処理せずに完了する.
                """
                _ = payload
                _ = user_id

        dispatcher = PacketDispatcher()
        group = MyHandlers()
        group.register_all(dispatcher)

        registered = dispatcher.get_handlers()
        assert ClientPacketID.PONG in registered

    def test_register_all_registers_multiple_handlers(self) -> None:
        """複数の@handles methodがすべて登録されることを検証する.

        PONGとEXITのhandlerを持つgroupへregister_allを実行し両packet IDがhandler集合にあることを
        確認する.

        Returns:
            None: 複数handler登録の検証を完了する.
        """

        class MyHandlers(HandlerGroup):
            """PONGとEXIT packetを登録するtest用HandlerGroup."""

            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                """PONG packetを受け取る登録専用handler.

                Args:
                    payload (bytes): dispatcherから渡されるpacket payload.
                    user_id (int): packet送信userのID.

                Returns:
                    None: payloadを処理せずに完了する.
                """
                _ = payload
                _ = user_id

            @handles(ClientPacketID.EXIT)
            async def handle_exit(self, payload: bytes, user_id: int) -> None:
                """EXIT packetを受け取る登録専用handler.

                Args:
                    payload (bytes): dispatcherから渡されるpacket payload.
                    user_id (int): packet送信userのID.

                Returns:
                    None: payloadを処理せずに完了する.
                """
                _ = payload
                _ = user_id

        dispatcher = PacketDispatcher()
        group = MyHandlers()
        group.register_all(dispatcher)

        registered = dispatcher.get_handlers()
        assert ClientPacketID.PONG in registered
        assert ClientPacketID.EXIT in registered

    async def test_registered_handler_is_bound_method(self) -> None:
        """登録済みhandlerがgroup instanceへboundされたmethodであることを検証する.

        PONG handlerを登録してpayloadとuser IDでdispatchしouter capture listへ一回だけ同じ値が
        記録されることを確認する.

        Returns:
            None: bound method dispatchの検証を完了する.
        """
        called_with: list[tuple[bytes, int]] = []

        class MyHandlers(HandlerGroup):
            """呼出し引数をcaptureするPONG handler用group."""

            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                """PONG packetの呼出し値をouter listへ記録する.

                Args:
                    payload (bytes): dispatchに渡されたpacket payload.
                    user_id (int): dispatchに渡されたuser ID.

                Returns:
                    None: payloadとuser IDの組をcaptureして完了する.
                """
                called_with.append((payload, user_id))

        dispatcher = PacketDispatcher()
        group = MyHandlers()
        group.register_all(dispatcher)

        await dispatcher.dispatch(ClientPacketID.PONG, b"\x00", 42)
        assert len(called_with) == 1
        assert called_with[0] == (b"\x00", 42)


class TestRegisterAllLogging:
    """register_allのregistration logとempty group warningを検証するtest群."""

    def test_register_all_logs_handlers_registered(self) -> None:
        """成功した登録がhandlers_registered logを一件発行することを検証する.

        PONG handlerを持つgroupをcapture_logs内で登録しgroup名とcountを持つeventが一件
        得られることを確認する.

        Returns:
            None: registration log内容の検証を完了する.
        """

        class MyHandlers(HandlerGroup):
            """registration logを検証するPONG handler用group."""

            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                """PONG packetを受け取るlogging検証用handler.

                Args:
                    payload (bytes): dispatcherから渡されるpacket payload.
                    user_id (int): packet送信userのID.

                Returns:
                    None: payloadを処理せずに完了する.
                """
                _ = payload
                _ = user_id

        dispatcher = PacketDispatcher()
        group = MyHandlers()

        with structlog.testing.capture_logs() as logs:
            group.register_all(dispatcher)

        reg_logs = [entry for entry in logs if entry.get("event") == "handlers_registered"]
        assert len(reg_logs) == 1
        assert reg_logs[0]["group"] == "MyHandlers"
        assert reg_logs[0]["count"] == 1

    def test_register_all_logs_correct_count(self) -> None:
        """登録logのcountが登録handler数と一致することを検証する.

        二つのhandlerを持つgroupをcapture_logs内で登録しhandlers_registered eventのcountが2に
        なることを確認する.

        Returns:
            None: registration countの検証を完了する.
        """

        class MultiHandlers(HandlerGroup):
            """二つのpacket handlerを登録するlogging検証用group."""

            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                """PONG packetを受け取るlogging検証用handler.

                Args:
                    payload (bytes): dispatcherから渡されるpacket payload.
                    user_id (int): packet送信userのID.

                Returns:
                    None: payloadを処理せずに完了する.
                """
                _ = payload
                _ = user_id

            @handles(ClientPacketID.EXIT)
            async def handle_exit(self, payload: bytes, user_id: int) -> None:
                """EXIT packetを受け取るlogging検証用handler.

                Args:
                    payload (bytes): dispatcherから渡されるpacket payload.
                    user_id (int): packet送信userのID.

                Returns:
                    None: payloadを処理せずに完了する.
                """
                _ = payload
                _ = user_id

        dispatcher = PacketDispatcher()
        group = MultiHandlers()

        with structlog.testing.capture_logs() as logs:
            group.register_all(dispatcher)

        reg_logs = [entry for entry in logs if entry.get("event") == "handlers_registered"]
        assert reg_logs[0]["count"] == 2

    def test_register_all_warns_on_empty_group(self) -> None:
        """handlerを持たないgroupがwarning logを発行することを検証する.

        空のgroupをcapture_logs内で登録しwarning levelのeventが一件とそのgroup名を持つことを
        確認する.

        Returns:
            None: empty group warningの検証を完了する.
        """

        class EmptyHandlers(HandlerGroup):
            """handlerを定義しないwarning検証用HandlerGroup."""

        dispatcher = PacketDispatcher()
        group = EmptyHandlers()

        with structlog.testing.capture_logs() as logs:
            group.register_all(dispatcher)

        warn_logs = [entry for entry in logs if entry.get("log_level") == "warning"]
        assert len(warn_logs) == 1
        assert warn_logs[0]["group"] == "EmptyHandlers"


class TestDuplicateHandlerError:
    """重複packet ID登録時のDuplicateHandlerErrorを検証するtest群."""

    def test_duplicate_packet_id_raises(self) -> None:
        """同じpacket IDを二つのgroupへ登録すると例外になることを検証する.

        PONG handlerを持つ最初のgroupを登録後に二つ目を登録し
        DuplicateHandlerErrorが送出されることを確認する.

        Returns:
            None: 重複packet ID拒否の検証を完了する.
        """

        class GroupA(HandlerGroup):
            """最初にPONG packetを登録する重複検出用group."""

            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                """PONG packetを受け取る重複検出用handler.

                Args:
                    payload (bytes): dispatcherから渡されるpacket payload.
                    user_id (int): packet送信userのID.

                Returns:
                    None: payloadを処理せずに完了する.
                """
                _ = payload
                _ = user_id

        class GroupB(HandlerGroup):
            """重複するPONG packetを登録する重複検出用group."""

            @handles(ClientPacketID.PONG)
            async def handle_pong(self, payload: bytes, user_id: int) -> None:
                """PONG packetを受け取る重複検出用handler.

                Args:
                    payload (bytes): dispatcherから渡されるpacket payload.
                    user_id (int): packet送信userのID.

                Returns:
                    None: payloadを処理せずに完了する.
                """
                _ = payload
                _ = user_id

        dispatcher = PacketDispatcher()
        group_a = GroupA()
        group_a.register_all(dispatcher)

        group_b = GroupB()
        with pytest.raises(DuplicateHandlerError):
            group_b.register_all(dispatcher)

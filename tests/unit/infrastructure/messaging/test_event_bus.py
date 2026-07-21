"""ローカルイベント配信の契約と例外隔離を検証します."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.messaging.memory import InMemoryLocalEventBus


@dataclass(slots=True)
class _UserLoggedIn:
    """ログイン済み user を通知するテスト用イベントです.

    Attributes:
        user_id (int): ログインした user の識別子です.
    """

    user_id: int


@dataclass(slots=True)
class _ChatMessageSent:
    """送信済み chat message を通知するテスト用イベントです.

    Attributes:
        sender_id (int): message を送信した user の識別子です.
        text (str): 送信された message 本文です.
    """

    sender_id: int
    text: str


@pytest.fixture
def bus() -> InMemoryLocalEventBus:
    """各testへ handler 未登録のローカルイベントバスを提供します.

    Returns:
        InMemoryLocalEventBus: 独立して購読と配信を検証できる空のイベントバスです.
    """
    return InMemoryLocalEventBus()


class TestProtocolCompliance:
    """実装が LocalEventBus protocol を満たすことを検証します."""

    def test_is_local_event_bus(self, bus: InMemoryLocalEventBus) -> None:
        """実装済みバスが runtime-checkable protocol と判定されることを検証します.

        Args:
            bus (InMemoryLocalEventBus): protocol 適合性を検証するローカルイベントバスです.

        Returns:
            None: isinstance による protocol 判定が成功したことを表します.
        """
        assert isinstance(bus, LocalEventBus)


class TestFireAndSubscribe:
    """イベントの購読、型選別、購読者不在時の配信を検証します."""

    async def test_handler_receives_event(self, bus: InMemoryLocalEventBus) -> None:
        """購読済みhandlerが同じ具象型のイベントを一回受け取ることを検証します.

        Args:
            bus (InMemoryLocalEventBus): handler 登録と配信に使うイベントバスです.

        Returns:
            None: 受信した user ID が送信イベントと一致することを表します.
        """
        received: list[_UserLoggedIn] = []

        async def on_login(event: _UserLoggedIn) -> None:
            """受信したログインイベントを観測用一覧へ追加します.

            Args:
                event (_UserLoggedIn): 配信されたログインイベントです.

            Returns:
                None: 観測用一覧への追加が完了したことを表します.
            """
            received.append(event)

        bus.subscribe(_UserLoggedIn, on_login)
        await bus.fire(_UserLoggedIn(user_id=1))

        assert len(received) == 1
        assert received[0].user_id == 1

    async def test_fire_without_subscribers_is_noop(self, bus: InMemoryLocalEventBus) -> None:
        """購読者がいないイベント配信が例外なく完了することを検証します.

        Args:
            bus (InMemoryLocalEventBus): 購読者を登録しないイベントバスです.

        Returns:
            None: no-op 配信が例外を送出しないことを表します.
        """
        await bus.fire(_UserLoggedIn(user_id=1))

    async def test_handler_only_receives_subscribed_type(
        self,
        bus: InMemoryLocalEventBus,
    ) -> None:
        """異なる具象型のイベントが登録外handlerへ渡らないことを検証します.

        Args:
            bus (InMemoryLocalEventBus): 型別の購読と配信に使うイベントバスです.

        Returns:
            None: login handler の観測一覧が空のままであることを表します.
        """
        received: list[object] = []

        async def on_login(event: _UserLoggedIn) -> None:
            """誤配送の有無を調べるためログインイベントを観測一覧へ追加します.

            Args:
                event (_UserLoggedIn): 配信されたログインイベントです.

            Returns:
                None: 観測用一覧への追加が完了したことを表します.
            """
            received.append(event)

        bus.subscribe(_UserLoggedIn, on_login)
        await bus.fire(_ChatMessageSent(sender_id=1, text="hello"))

        assert len(received) == 0


class TestMultipleHandlers:
    """複数handlerと複数イベント型の配信分離を検証します."""

    async def test_multiple_handlers_called_in_order(self, bus: InMemoryLocalEventBus) -> None:
        """同じ型のhandlerが登録順に一度ずつ呼ばれることを検証します.

        Args:
            bus (InMemoryLocalEventBus): 三つのhandlerを登録して配信するイベントバスです.

        Returns:
            None: 観測したhandler名が登録順と一致することを表します.
        """
        order: list[str] = []

        async def first(_event: _UserLoggedIn) -> None:
            """一番目のhandler呼び出しを観測順へ記録します.

            Args:
                _event (_UserLoggedIn): 順序検証のために配信されたログインイベントです.

            Returns:
                None: 一番目の識別子を記録したことを表します.
            """
            order.append("first")

        async def second(_event: _UserLoggedIn) -> None:
            """二番目のhandler呼び出しを観測順へ記録します.

            Args:
                _event (_UserLoggedIn): 順序検証のために配信されたログインイベントです.

            Returns:
                None: 二番目の識別子を記録したことを表します.
            """
            order.append("second")

        async def third(_event: _UserLoggedIn) -> None:
            """三番目のhandler呼び出しを観測順へ記録します.

            Args:
                _event (_UserLoggedIn): 順序検証のために配信されたログインイベントです.

            Returns:
                None: 三番目の識別子を記録したことを表します.
            """
            order.append("third")

        bus.subscribe(_UserLoggedIn, first)
        bus.subscribe(_UserLoggedIn, second)
        bus.subscribe(_UserLoggedIn, third)

        await bus.fire(_UserLoggedIn(user_id=1))

        assert order == ["first", "second", "third"]

    async def test_multiple_event_types(self, bus: InMemoryLocalEventBus) -> None:
        """各イベント型が対応するhandlerだけへ配信されることを検証します.

        Args:
            bus (InMemoryLocalEventBus): 二つのイベント型を購読して配信するイベントバスです.

        Returns:
            None: login と chat の各観測一覧に一件ずつ入ることを表します.
        """
        logins: list[_UserLoggedIn] = []
        chats: list[_ChatMessageSent] = []

        async def on_login(event: _UserLoggedIn) -> None:
            """ログインイベントを対応する観測一覧へ追加します.

            Args:
                event (_UserLoggedIn): 配信されたログインイベントです.

            Returns:
                None: login 観測一覧への追加が完了したことを表します.
            """
            logins.append(event)

        async def on_chat(event: _ChatMessageSent) -> None:
            """chatイベントを対応する観測一覧へ追加します.

            Args:
                event (_ChatMessageSent): 配信されたchatイベントです.

            Returns:
                None: chat 観測一覧への追加が完了したことを表します.
            """
            chats.append(event)

        bus.subscribe(_UserLoggedIn, on_login)
        bus.subscribe(_ChatMessageSent, on_chat)

        await bus.fire(_UserLoggedIn(user_id=1))
        await bus.fire(_ChatMessageSent(sender_id=2, text="hi"))

        assert len(logins) == 1
        assert len(chats) == 1


class TestExceptionIsolation:
    """handler例外の隔離とlog記録を検証します."""

    async def test_handler_exception_does_not_stop_others(
        self,
        bus: InMemoryLocalEventBus,
    ) -> None:
        """失敗handlerの後も後続handlerが実行されることを検証します.

        Args:
            bus (InMemoryLocalEventBus): 失敗handlerと成功handlerを登録するイベントバスです.

        Returns:
            None: 後続handlerの観測結果が記録されることを表します.
        """
        results: list[str] = []

        async def failing(_event: _UserLoggedIn) -> None:
            """例外隔離を検証するため常にRuntimeErrorを送出します.

            Args:
                _event (_UserLoggedIn): 失敗handlerへ配信されたログインイベントです.

            Raises:
                RuntimeError: handler error を意図的に送出します.
            """
            msg = "handler error"
            raise RuntimeError(msg)

        async def succeeding(_event: _UserLoggedIn) -> None:
            """後続handlerの実行を示す値を観測一覧へ追加します.

            Args:
                _event (_UserLoggedIn): 成功handlerへ配信されたログインイベントです.

            Returns:
                None: 成功を示す値を記録したことを表します.
            """
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
        """失敗handlerの例外情報がerror logに記録されることを検証します.

        Args:
            bus (InMemoryLocalEventBus): 例外を送出するhandlerを登録するイベントバスです.
            caplog (pytest.LogCaptureFixture): error log と例外情報を観測するfixtureです.

        Returns:
            None: handler名と例外情報を含むerror logが観測されることを表します.
        """

        async def failing(_event: _UserLoggedIn) -> None:
            """log記録を検証するため常にValueErrorを送出します.

            Args:
                _event (_UserLoggedIn): 失敗handlerへ配信されたログインイベントです.

            Raises:
                ValueError: boom を意図的に送出します.
            """
            msg = "boom"
            raise ValueError(msg)

        bus.subscribe(_UserLoggedIn, failing)

        with caplog.at_level("ERROR"):
            await bus.fire(_UserLoggedIn(user_id=1))

        assert any("failing" in record.message for record in caplog.records)
        assert any(record.exc_info is not None for record in caplog.records)


class TestLocalOnlyContract:
    """LocalEventBusのローカル限定契約説明を検証します."""

    def test_contract_names_local_scope(self) -> None:
        """公開docstringがローカル限定のcross-replica制約を示すことを検証します.

        Returns:
            None: protocol名と既存contract phraseが維持されていることを表します.
        """
        assert LocalEventBus.__name__ == "LocalEventBus"
        assert "cross-replica" in (LocalEventBus.__doc__ or "")

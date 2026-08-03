"""ListenerGroupのrouting継承とevent登録とlogging契約を検証する."""

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
    """listener登録を検証する最小のeventを表す.

    Attributes:
        value (int): listenerが受信した値を識別する整数.
    """

    value: int


@dataclass(frozen=True, slots=True)
class AnotherEvent:
    """複数event型の登録を検証する補助eventを表す.

    Attributes:
        data (str): event型ごとの配送結果を区別する文字列.
    """

    data: str


class TestListenerGroupIsRouteGroup:
    """ListenerGroupのrouting基底class契約を検証する."""

    def test_listener_group_is_subclass_of_route_group(self) -> None:
        """ListenerGroupがRouteGroup互換である契約を検証する.

        基底classを比較し,listener groupがroutingの共通走査機構を継承することを確認する.

        Returns:
            None: 継承関係を検証して完了し,呼び出し側へ値を返さない.
        """
        assert issubclass(ListenerGroup, RouteGroup)

    def test_listens_is_route_alias(self) -> None:
        """Listens decoratorがroute decoratorと同一である契約を検証する.

        decorator objectを比較する.
        listener登録がhandler routingと同じmetadata形式を使うことを確認する.

        Returns:
            None: aliasの同一性を検証して完了し,呼び出し側へ値を返さない.
        """
        assert listens is route


class TestRegisterAll:
    """register_allが宣言済みlistenerをevent busへ登録する契約を検証する."""

    async def test_register_all_subscribes_listeners(self) -> None:
        """単一listenerがevent fire後に呼び出される契約を検証する.

        FakeEventを購読するgroupを登録してeventをfireする.
        同じevent instanceが受信記録へ追加されることを確認する.

        Returns:
            None: 配送結果を検証して完了し,呼び出し側へ値を返さない.
        """
        received: list[FakeEvent] = []

        class MyListeners(ListenerGroup):
            """単一FakeEventの配送結果を記録するtest listener groupを表す."""

            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                """受信したFakeEventを検証用listへ記録する.

                Args:
                    event (FakeEvent): event busが配送したevent.

                Returns:
                    None: eventを記録して完了し,呼び出し側へ値を返さない.
                """
                received.append(event)

        event_bus = InMemoryLocalEventBus()
        group = MyListeners()
        group.register_all(event_bus)

        event = FakeEvent(value=42)
        await event_bus.fire(event)

        assert len(received) == 1
        assert received[0] is event

    async def test_register_all_subscribes_multiple_listeners(self) -> None:
        """異なるevent型の全listenerが個別に購読される契約を検証する.

        2種類のeventを購読するgroupを登録して順にfireし,各listenerの受信listだけが1件になることを確認する.

        Returns:
            None: 型別の配送結果を検証して完了し,呼び出し側へ値を返さない.
        """
        fake_received: list[FakeEvent] = []
        another_received: list[AnotherEvent] = []

        class MyListeners(ListenerGroup):
            """2種類のeventを別々のlistへ記録するtest listener groupを表す."""

            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                """FakeEventを対応する検証用listへ記録する.

                Args:
                    event (FakeEvent): 配送されたFakeEvent.

                Returns:
                    None: eventを記録して完了し,呼び出し側へ値を返さない.
                """
                fake_received.append(event)

            @listens(AnotherEvent)
            async def on_another(self, event: AnotherEvent) -> None:
                """AnotherEventを対応する検証用listへ記録する.

                Args:
                    event (AnotherEvent): 配送されたAnotherEvent.

                Returns:
                    None: eventを記録して完了し,呼び出し側へ値を返さない.
                """
                another_received.append(event)

        event_bus = InMemoryLocalEventBus()
        group = MyListeners()
        group.register_all(event_bus)

        await event_bus.fire(FakeEvent(value=1))
        await event_bus.fire(AnotherEvent(data="hello"))

        assert len(fake_received) == 1
        assert len(another_received) == 1

    async def test_registered_listener_is_bound_method(self) -> None:
        """登録済みlistenerがinstance stateを持つbound methodである契約を検証する.

        multiplierを持つgroupを登録してeventをfireし,listenerがinstanceの倍率で値を変換した結果を記録することを確認する.

        Returns:
            None: bound methodの結果を検証して完了し,呼び出し側へ値を返さない.
        """
        results: list[int] = []

        @final
        class MyListeners(ListenerGroup):
            """instance倍率を受信値へ適用するtest listener groupを表す.

            Attributes:
                multiplier (int): 受信event値へ適用するinstance固有の倍率.
            """

            def __init__(self, multiplier: int) -> None:
                """event値の検証用倍率を初期化する.

                Args:
                    multiplier (int): 受信値へ適用する倍率.
                """
                self.multiplier = multiplier

            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                """instanceの倍率を適用したevent値を記録する.

                Args:
                    event (FakeEvent): 倍率を適用する配送event.

                Returns:
                    None: 変換結果を記録して完了し,呼び出し側へ値を返さない.
                """
                results.append(event.value * self.multiplier)

        event_bus = InMemoryLocalEventBus()
        group = MyListeners(multiplier=10)
        group.register_all(event_bus)

        await event_bus.fire(FakeEvent(value=3))
        assert results == [30]


class TestRegisterAllLogging:
    """register_allが登録数と空groupをログへ表す契約を検証する."""

    def test_register_all_logs_listeners_registered(self) -> None:
        """listenerを登録したときに成功event logを出す契約を検証する.

        listenerを1件持つgroupを登録する.
        captured logにgroup名とcountを持つlisteners_registered eventが1件出ることを確認する.

        Returns:
            None: 成功logを検証して完了し,呼び出し側へ値を返さない.
        """

        class MyListeners(ListenerGroup):
            """成功logを確認するための単一listener groupを表す."""

            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                """登録対象のeventを消費してtest listenerを完了する.

                Args:
                    event (FakeEvent): event busが配送するevent.

                Returns:
                    None: eventを消費して完了し,呼び出し側へ値を返さない.
                """
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
        """成功logのcountが登録listener数と一致する契約を検証する.

        listenerを2件持つgroupを登録し,listeners_registered eventのcountが2になることを確認する.

        Returns:
            None: 登録数logを検証して完了し,呼び出し側へ値を返さない.
        """

        class MultiListeners(ListenerGroup):
            """成功logの登録数を確認するための複数listener groupを表す."""

            @listens(FakeEvent)
            async def on_fake(self, event: FakeEvent) -> None:
                """FakeEventを消費してtest listenerを完了する.

                Args:
                    event (FakeEvent): event busが配送するevent.

                Returns:
                    None: eventを消費して完了し,呼び出し側へ値を返さない.
                """
                _ = event

            @listens(AnotherEvent)
            async def on_another(self, event: AnotherEvent) -> None:
                """AnotherEventを消費してtest listenerを完了する.

                Args:
                    event (AnotherEvent): event busが配送するevent.

                Returns:
                    None: eventを消費して完了し,呼び出し側へ値を返さない.
                """
                _ = event

        event_bus = InMemoryLocalEventBus()
        group = MultiListeners()

        with structlog.testing.capture_logs() as logs:
            group.register_all(event_bus)

        reg_logs = [entry for entry in logs if entry.get("event") == "listeners_registered"]
        assert reg_logs[0]["count"] == 2

    def test_register_all_warns_on_empty_group(self) -> None:
        """listenerを持たないgroupがwarning logを出す契約を検証する.

        空groupを登録し,captured logにwarning levelとgroup名を持つentryが1件出ることを確認する.

        Returns:
            None: 空groupのwarningを検証して完了し,呼び出し側へ値を返さない.
        """

        class EmptyListeners(ListenerGroup):
            """warning logを確認するためにlistenerを持たないgroupを表す."""

        event_bus = InMemoryLocalEventBus()
        group = EmptyListeners()

        with structlog.testing.capture_logs() as logs:
            group.register_all(event_bus)

        warn_logs = [entry for entry in logs if entry.get("log_level") == "warning"]
        assert len(warn_logs) == 1
        assert warn_logs[0]["group"] == "EmptyListeners"


class TestSymmetryWithHandlerGroup:
    """ListenerGroupとHandlerGroupの構造的対称性を検証する."""

    def test_both_extend_route_group(self) -> None:
        """両groupがRouteGroupを継承する対称性を検証する.

        HandlerGroupとListenerGroupを同じ基底classに対して検査し,routing走査契約が共通であることを確認する.

        Returns:
            None: 継承関係を検証して完了し,呼び出し側へ値を返さない.
        """
        assert issubclass(HandlerGroup, RouteGroup)
        assert issubclass(ListenerGroup, RouteGroup)

    def test_both_have_register_all(self) -> None:
        """両groupがregister_all APIを公開する対称性を検証する.

        両classのattributeを検査し,handlerとlistenerが同じ登録entry pointを持つことを確認する.

        Returns:
            None: 公開APIを検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(HandlerGroup, "register_all")
        assert hasattr(ListenerGroup, "register_all")

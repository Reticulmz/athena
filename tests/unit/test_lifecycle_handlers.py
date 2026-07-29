"""LifecycleHandlersのPONGとEXIT packet処理を検証するmodule.

session削除とUserDisconnected event発行およびevent bus failure時のfinally契約を対象にする.
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
    """LifecycleHandlers test用に削除要求を記録するSessionStore fake.

    Attributes:
        deleted_users (list[int]): delete_by_userへ渡されたuser IDを呼出し順で保持する.

    Notes:
        delete_by_user以外のSessionStore APIはこのtestで利用しないため
        NotImplementedErrorを送出する.
    """

    def __init__(self) -> None:
        """削除済みuser IDを持たない初期状態でfakeを生成する."""
        self.deleted_users: list[int] = []

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """未使用のsession作成APIを明示的に拒否する.

        Args:
            user_id (int): 作成対象userのID.
            token (str): session識別token.
            data (SessionData): 保存するsession data.

        Returns:
            None: 値を返さずに完了する型契約を表す.

        Raises:
            NotImplementedError: lifecycle handler testではsession作成を扱わない場合.
        """
        _ = (user_id, token, data)
        raise NotImplementedError

    async def get(self, token: str) -> SessionData | None:
        """未使用のtoken検索APIを明示的に拒否する.

        Args:
            token (str): 検索対象のsession識別token.

        Returns:
            SessionData | None: session dataまたは見つからない場合のNoneを表す型契約.

        Raises:
            NotImplementedError: lifecycle handler testではtoken検索を扱わない場合.
        """
        _ = token
        raise NotImplementedError

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """未使用のuser別session検索APIを明示的に拒否する.

        Args:
            user_id (int): 検索対象userのID.

        Returns:
            SessionData | None: session dataまたは見つからない場合のNoneを表す型契約.

        Raises:
            NotImplementedError: lifecycle handler testではuser別検索を扱わない場合.
        """
        _ = user_id
        raise NotImplementedError

    async def delete(self, token: str) -> None:
        """未使用のtoken別削除APIを明示的に拒否する.

        Args:
            token (str): 削除対象のsession識別token.

        Returns:
            None: 値を返さずに完了する型契約を表す.

        Raises:
            NotImplementedError: lifecycle handler testではtoken別削除を扱わない場合.
        """
        _ = token
        raise NotImplementedError

    async def exists(self, token: str) -> bool:
        """未使用のsession存在確認APIを明示的に拒否する.

        Args:
            token (str): 確認対象のsession識別token.

        Returns:
            bool: sessionが存在するかを表す型契約.

        Raises:
            NotImplementedError: lifecycle handler testでは存在確認を扱わない場合.
        """
        _ = token
        raise NotImplementedError

    async def refresh(self, token: str) -> bool:
        """未使用のsession更新APIを明示的に拒否する.

        Args:
            token (str): 更新対象のsession識別token.

        Returns:
            bool: 更新されたsessionがあるかを表す型契約.

        Raises:
            NotImplementedError: lifecycle handler testではsession更新を扱わない場合.
        """
        _ = token
        raise NotImplementedError

    async def delete_by_user(self, user_id: int) -> None:
        """user別session削除要求を記録する.

        Args:
            user_id (int): EXIT packetで削除するuserのID.

        Returns:
            None: user IDをdeleted_usersへ追加して完了する.
        """
        self.deleted_users.append(user_id)

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """未使用のauthorization更新APIを明示的に拒否する.

        Args:
            user_id (int): 更新対象userのID.
            authorization (SessionAuthorization): 保存するauthorization snapshot.

        Returns:
            bool: 更新されたsessionがあるかを表す型契約.

        Raises:
            NotImplementedError: lifecycle handler testではauthorization更新を扱わない場合.
        """
        _ = (user_id, authorization)
        raise NotImplementedError

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        """未使用のprivate message設定更新APIを明示的に拒否する.

        Args:
            user_id (int): 更新対象userのID.
            enabled (bool): private message受信を許可するか.

        Returns:
            bool: 更新されたsessionがあるかを表す型契約.

        Raises:
            NotImplementedError: lifecycle handler testでは設定更新を扱わない場合.
        """
        _ = (user_id, enabled)
        raise NotImplementedError

    async def list_active_sessions(self) -> list[SessionData]:
        """未使用のactive session列挙APIを明示的に拒否する.

        Returns:
            list[SessionData]: active sessionを順に返す型契約.

        Raises:
            NotImplementedError: lifecycle handler testではsession列挙を扱わない場合.
        """
        raise NotImplementedError


class FakeLocalEventBus:
    """LifecycleHandlers test用に発行eventを記録するLocalEventBus fake.

    Attributes:
        fired_events (list[object]): fireが正常終了したeventを呼出し順で保持する.
        raise_on_fire (Exception | None): 設定時にfireから送出する例外.
    """

    def __init__(self) -> None:
        """event記録と例外注入を持たない初期状態でfakeを生成する."""
        self.fired_events: list[object] = []
        self.raise_on_fire: Exception | None = None

    async def fire(self, event: object) -> None:
        """eventを記録するか設定済みの例外を送出する.

        Args:
            event (object): LocalEventBusへ発行するdomain event.

        Returns:
            None: 正常時にeventをfired_eventsへ追加して完了する.
        """
        if self.raise_on_fire:
            raise self.raise_on_fire
        self.fired_events.append(event)

    def subscribe(
        self,
        event_type: type[TEvent],
        handler: Callable[[TEvent], Awaitable[None]],
    ) -> None:
        """未使用のevent購読APIを明示的に拒否する.

        Args:
            event_type (type[TEvent]): 購読対象のevent型.
            handler (Callable[[TEvent], Awaitable[None]]): event受信時にawaitするhandler.

        Returns:
            None: 値を返さずに完了する型契約を表す.

        Raises:
            NotImplementedError: lifecycle handler testではevent購読を扱わない場合.
        """
        _ = (event_type, handler)
        raise NotImplementedError


@pytest.fixture
def session_store() -> FakeSessionStore:
    """削除user IDを記録できるSessionStore fakeを提供する.

    Returns:
        FakeSessionStore: testごとに独立した空の削除記録を持つfake.
    """
    return FakeSessionStore()


@pytest.fixture
def event_bus() -> FakeLocalEventBus:
    """event発行とfailure注入を観測できるLocalEventBus fakeを提供する.

    Returns:
        FakeLocalEventBus: testごとに独立したevent記録を持つfake.
    """
    return FakeLocalEventBus()


@pytest.fixture
def handlers(session_store: FakeSessionStore, event_bus: FakeLocalEventBus) -> LifecycleHandlers:
    """fake依存を注入したLifecycleHandlersを提供する.

    Args:
        session_store (FakeSessionStore): EXITによるsession削除を記録するfake.
        event_bus (FakeLocalEventBus): UserDisconnected発行を記録するfake.

    Returns:
        LifecycleHandlers: 二つのfakeへ副作用を向けるhandler instance.
    """
    return LifecycleHandlers(
        session_store=session_store,
        event_bus=event_bus,
    )


class TestHandlePong:
    """PONG packetの正常完了とquiet logging設定を検証するtest群."""

    async def test_handle_pong_completes_without_error(self, handlers: LifecycleHandlers) -> None:
        """空payloadのPONG処理が例外なく完了することを検証する.

        Args:
            handlers (LifecycleHandlers): fake依存を持つPONG handler.

        空bytesとuser ID 1を渡してhandle_pongをawaitし正常に戻ることを確認する.

        Returns:
            None: PONG正常完了の検証を完了する.
        """
        await handlers.handle_pong(b"", 1)

    async def test_handle_pong_completes_with_arbitrary_payload(
        self, handlers: LifecycleHandlers
    ) -> None:
        """任意内容のPONG payloadが例外なく無視されることを検証する.

        Args:
            handlers (LifecycleHandlers): fake依存を持つPONG handler.

        64 byteの非ASCII payloadとuser ID 999を渡してhandle_pongをawaitし正常に戻ることを確認する.

        Returns:
            None: 任意payload受理の検証を完了する.
        """
        await handlers.handle_pong(b"\xff" * 64, 999)

    def test_pong_is_in_quiet_packets(self) -> None:
        """PONGがquiet C2S packet集合に含まれることを検証する.

        ClientPacketID.PONGをQUIET_C2S_PACKETSへ照会しDEBUG-level logging対象であることを確認する.

        Returns:
            None: quiet packet設定の検証を完了する.
        """
        assert ClientPacketID.PONG in QUIET_C2S_PACKETS


class TestHandleExit:
    """EXIT packetのevent発行とsession削除を検証するtest群."""

    async def test_exit_fires_user_disconnected_event(
        self, handlers: LifecycleHandlers, event_bus: FakeLocalEventBus
    ) -> None:
        """EXITが対象user IDを持つUserDisconnected eventを発行することを検証する.

        Args:
            handlers (LifecycleHandlers): fake依存を持つEXIT handler.
            event_bus (FakeLocalEventBus): 発行eventを記録するfake.

        user ID 42でhandle_exitをawaitし記録eventが一件で同じuser IDを持つことを確認する.

        Returns:
            None: disconnect event発行の検証を完了する.
        """
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
        """EXITが対象userのsession削除を要求することを検証する.

        Args:
            handlers (LifecycleHandlers): fake依存を持つEXIT handler.
            session_store (FakeSessionStore): 削除要求を記録するfake.

        user ID 42でhandle_exitをawaitしdeleted_usersが42だけを呼出し順で持つことを確認する.

        Returns:
            None: session削除要求の検証を完了する.
        """
        await handlers.handle_exit(b"", user_id=42)

        assert session_store.deleted_users == [42]


class TestHandleExitTryFinally:
    """event発行失敗時にもEXITがsessionを削除することを検証するtest群."""

    async def test_session_deleted_when_event_fire_raises(
        self,
        session_store: FakeSessionStore,
        event_bus: FakeLocalEventBus,
    ) -> None:
        """LocalEventBus.fireが例外でもsession削除が実行されることを検証する.

        Args:
            session_store (FakeSessionStore): 削除要求を記録するfake.
            event_bus (FakeLocalEventBus): RuntimeErrorを注入するfake event bus.

        event busにRuntimeErrorを設定してuser ID 7のEXITをawaitし例外後も
        deleted_usersに7が残ることを確認する.

        Returns:
            None: finally内session削除の検証を完了する.
        """
        event_bus.raise_on_fire = RuntimeError("event bus failure")
        handler = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )

        with pytest.raises(RuntimeError, match="event bus failure"):
            await handler.handle_exit(b"", user_id=7)

        assert session_store.deleted_users == [7]


class TestHandleExitIdempotency:
    """同じuserへの複数EXIT処理が正常完了することを検証するtest群."""

    async def test_double_exit_no_error(
        self, handlers: LifecycleHandlers, session_store: FakeSessionStore
    ) -> None:
        """同じuser IDへの二回のEXITが例外なく削除要求を記録することを検証する.

        Args:
            handlers (LifecycleHandlers): fake依存を持つEXIT handler.
            session_store (FakeSessionStore): 削除要求を記録するfake.

        user ID 10でhandle_exitを二回awaitしdeleted_usersが同じIDを二回保持することを確認する.

        Returns:
            None: EXIT idempotencyの検証を完了する.
        """
        await handlers.handle_exit(b"", user_id=10)
        await handlers.handle_exit(b"", user_id=10)

        assert session_store.deleted_users == [10, 10]

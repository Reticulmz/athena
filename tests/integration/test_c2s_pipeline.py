"""C2S handler pipelineの統合契約を検証する.

実メモリ実装でEXIT処理とhandler/listener登録を接続する.
packet配信と未登録入力の取り扱いを確認する.
"""

from __future__ import annotations

import struct

from osu_server.domain.events.base import Event
from osu_server.domain.events.users import UserDisconnected
from osu_server.domain.identity.sessions import SessionData
from osu_server.infrastructure.messaging.memory import InMemoryLocalEventBus
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.services.queries.identity import (
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryUseCase,
)
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.stable.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID, ServerPacketID

# ── Constants ───────────────────────────────────────────────────────

_HEADER_FMT = struct.Struct("<HBI")
_INT32_FMT = struct.Struct("<i")
_PACKET_QUEUE_TTL = 300


def _make_session_data(user_id: int) -> SessionData:
    """テスト用の最小接続状態を生成する.

    Args:
        user_id (int): 生成する接続状態の利用者ID.

    Returns:
        SessionData: 指定した利用者IDと固定のstable client属性を持つ接続状態.
    """
    return SessionData(
        user_id=user_id,
        username=f"user_{user_id}",
        privileges=0,
        country="JP",
        osu_version="20231111",
        utc_offset=9,
        display_city=False,
        client_hashes="",
        pm_private=False,
    )


def _parse_s2c_header(data: bytes) -> tuple[int, int]:
    """S2C packet headerからpacket IDとpayload sizeを取り出す.

    Args:
        data (bytes): S2C packet headerで始まるbyte列.

    Returns:
        tuple[int, int]: compression flagを除いたpacket IDとpayload size.
    """
    unpacked: tuple[int, bool, int] = _HEADER_FMT.unpack_from(data)
    packet_id, _, size = unpacked
    return packet_id, size


# ═══════════════════════════════════════════════════════════════════
# Test 1: EXIT Pipeline Integration
# ═══════════════════════════════════════════════════════════════════


class TestExitPipelineIntegration:
    """EXIT処理からS2C切断通知までの統合契約を検証する."""

    async def test_exit_broadcasts_user_quit_to_other_users(self) -> None:
        """EXIT処理が他の接続利用者だけへUSER_QUITを配信することを検証する.

        3利用者のsessionとpacket queueを構築して利用者1のEXITを処理する.
        観測結果として利用者2と3だけが利用者1のIDを持つpacketを受信する.

        Returns:
            None: recipientごとのpacket配信契約を検証して終了する.
        """
        # Arrange: wire real components
        session_store = InMemorySessionStore()
        event_bus = InMemoryLocalEventBus()
        packet_queue = InMemoryPacketQueue()
        active_sessions_query = ListActiveSessionsQueryUseCase(session_store=session_store)

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        listeners = LifecycleListeners(
            active_sessions_query=active_sessions_query,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        # Create 3 sessions and activate their packet queues
        for uid in (1, 2, 3):
            await session_store.create(uid, f"token_{uid}", _make_session_data(uid))
            await packet_queue.refresh_ttl(uid, _PACKET_QUEUE_TTL)

        # Act: user 1 exits
        await handlers.handle_exit(b"", user_id=1)

        # Assert: user 2 and user 3 have USER_QUIT(user_id=1)
        for uid in (2, 3):
            data = await packet_queue.dequeue_all(uid)
            assert len(data) > 0, f"user {uid} should have received USER_QUIT"

            packet_id, payload_size = _parse_s2c_header(data)
            assert packet_id == ServerPacketID.USER_QUIT
            assert payload_size == 4

            payload = data[_HEADER_FMT.size :]
            quit_user_id = int.from_bytes(payload, byteorder="little", signed=True)
            assert quit_user_id == 1

        # User 1 should NOT receive their own USER_QUIT
        user1_data = await packet_queue.dequeue_all(1)
        assert user1_data == b""

    async def test_exit_deletes_session(self) -> None:
        """EXIT処理が切断利用者のsessionを削除することを検証する.

        接続済み利用者に対してlistener登録済みのhandlerを実行する.
        観測結果としてsession storeから対象利用者を取得できなくなる.

        Returns:
            None: session削除契約を検証して終了する.
        """
        session_store = InMemorySessionStore()
        event_bus = InMemoryLocalEventBus()
        packet_queue = InMemoryPacketQueue()
        active_sessions_query = ListActiveSessionsQueryUseCase(session_store=session_store)

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        listeners = LifecycleListeners(
            active_sessions_query=active_sessions_query,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        await session_store.create(1, "token_1", _make_session_data(1))
        await packet_queue.refresh_ttl(1, _PACKET_QUEUE_TTL)

        await handlers.handle_exit(b"", user_id=1)

        # Session should be deleted
        assert await session_store.get_by_user(1) is None

    async def test_exit_user_excluded_from_online_list_after_disconnect(self) -> None:
        """EXIT後に切断利用者がonline session一覧から除かれることを検証する.

        2利用者を接続させた後に片方のEXITを処理する.
        観測結果として切断利用者だけがactive session queryの結果から消える.

        Returns:
            None: disconnect後のonline session可視性を検証して終了する.
        """
        session_store = InMemorySessionStore()
        event_bus = InMemoryLocalEventBus()
        packet_queue = InMemoryPacketQueue()
        active_sessions_query = ListActiveSessionsQueryUseCase(session_store=session_store)

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        listeners = LifecycleListeners(
            active_sessions_query=active_sessions_query,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        for uid in (10, 20):
            await session_store.create(uid, f"token_{uid}", _make_session_data(uid))
            await packet_queue.refresh_ttl(uid, _PACKET_QUEUE_TTL)

        await handlers.handle_exit(b"", user_id=10)

        # user 10 is gone
        active_sessions = await active_sessions_query.execute(ListActiveSessionsQueryInput())
        all_ids = [session.user_id for session in active_sessions.sessions]
        assert 10 not in all_ids
        assert 20 in all_ids


# ═══════════════════════════════════════════════════════════════════
# Test 2: HandlerGroup + PacketDispatcher Integration
# ═══════════════════════════════════════════════════════════════════


class TestHandlerGroupDispatcherIntegration:
    """handler登録とPacketDispatcherの接続契約を検証する."""

    async def test_dispatch_calls_registered_handler(self) -> None:
        """登録済みPONGとEXITが対応するhandlerへdispatchされることを検証する.

        sessionを持つ利用者にLifecycleHandlersを登録して両packetをdispatchする.
        観測結果としてPONGは完了しEXITは対象sessionを削除する.

        Returns:
            None: 登録済みhandlerのdispatch結果を検証して終了する.
        """
        session_store = InMemorySessionStore()
        event_bus = InMemoryLocalEventBus()
        dispatcher = PacketDispatcher()

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        handlers.register_all(dispatcher)

        # Create a session so EXIT has something to delete
        await session_store.create(42, "token_42", _make_session_data(42))

        # Dispatch PONG — should not raise
        await dispatcher.dispatch(ClientPacketID.PONG, b"", user_id=42)

        # Dispatch EXIT — should delete session and fire event
        await dispatcher.dispatch(ClientPacketID.EXIT, b"", user_id=42)

        assert await session_store.get_by_user(42) is None

    async def test_unregistered_packet_is_ignored(self) -> None:
        """未登録packetが例外なしで無視されることを検証する.

        lifecycle handlerだけを登録したdispatcherへSEND_MESSAGEを渡す.
        観測結果として登録されていないpacketは処理されず正常に完了する.

        Returns:
            None: 未登録packetのno-op契約を検証して終了する.
        """
        session_store = InMemorySessionStore()
        event_bus = InMemoryLocalEventBus()
        dispatcher = PacketDispatcher()

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        handlers.register_all(dispatcher)

        # SEND_MESSAGE has no handler — should be silently ignored
        await dispatcher.dispatch(ClientPacketID.SEND_MESSAGE, b"\x00", user_id=1)

    async def test_all_lifecycle_handlers_registered(self) -> None:
        """register_allがPONGとEXITだけを登録することを検証する.

        LifecycleHandlersを空のdispatcherへ登録する.
        観測結果としてregistryは両packet IDを持ち期待する件数になる.

        Returns:
            None: lifecycle handler registryの内容を検証して終了する.
        """
        session_store = InMemorySessionStore()
        event_bus = InMemoryLocalEventBus()
        dispatcher = PacketDispatcher()

        handlers = LifecycleHandlers(
            session_store=session_store,
            event_bus=event_bus,
        )
        handlers.register_all(dispatcher)

        registered = dispatcher.get_handlers()
        assert ClientPacketID.PONG in registered
        assert ClientPacketID.EXIT in registered
        assert len(registered) == ClientPacketID.EXIT.value


# ═══════════════════════════════════════════════════════════════════
# Test 3: ListenerGroup + LocalEventBus Integration
# ═══════════════════════════════════════════════════════════════════


class TestListenerGroupLocalEventBusIntegration:
    """listener登録とLocalEventBusの接続契約を検証する."""

    async def test_fire_calls_registered_listener(self) -> None:
        """登録済みUserDisconnected listenerがUSER_QUITを配信することを検証する.

        packetを受信できるonline利用者を用意して切断eventをfireする.
        観測結果としてrecipient queueに切断利用者IDを持つUSER_QUITが入る.

        Returns:
            None: listenerによるS2C fan-out契約を検証して終了する.
        """
        session_store = InMemorySessionStore()
        packet_queue = InMemoryPacketQueue()
        event_bus = InMemoryLocalEventBus()
        active_sessions_query = ListActiveSessionsQueryUseCase(session_store=session_store)

        listeners = LifecycleListeners(
            active_sessions_query=active_sessions_query,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        # Set up an online user who should receive the broadcast
        await session_store.create(5, "token_5", _make_session_data(5))
        await packet_queue.refresh_ttl(5, _PACKET_QUEUE_TTL)

        # Fire event for user 99 disconnecting
        await event_bus.fire(UserDisconnected(user_id=99))

        # User 5 should have received USER_QUIT for user 99
        data = await packet_queue.dequeue_all(5)
        assert len(data) > 0

        packet_id, _ = _parse_s2c_header(data)
        assert packet_id == ServerPacketID.USER_QUIT

        payload = data[_HEADER_FMT.size :]
        quit_user_id = int.from_bytes(payload, byteorder="little", signed=True)
        assert quit_user_id == 99

    async def test_unsubscribed_event_type_is_ignored(self) -> None:
        """購読者のないeventが例外なしで無視されることを検証する.

        listenerを登録しないevent busへUserDisconnectedをfireする.
        観測結果としてevent busは副作用なく正常に完了する.

        Returns:
            None: 未購読eventのno-op契約を検証して終了する.
        """
        event_bus = InMemoryLocalEventBus()

        # No listeners registered — fire should be a no-op
        await event_bus.fire(UserDisconnected(user_id=1))

    async def test_listener_not_triggered_by_wrong_event_type(self) -> None:
        """LifecycleListenersがUserDisconnected以外へ反応しないことを検証する.

        online利用者を用意してbare Eventをfireする.
        観測結果としてrecipient queueにS2C packetは追加されない.

        Returns:
            None: event型によるlistener絞り込み契約を検証して終了する.
        """
        session_store = InMemorySessionStore()
        packet_queue = InMemoryPacketQueue()
        event_bus = InMemoryLocalEventBus()
        active_sessions_query = ListActiveSessionsQueryUseCase(session_store=session_store)

        listeners = LifecycleListeners(
            active_sessions_query=active_sessions_query,
            packet_queue=packet_queue,
        )
        listeners.register_all(event_bus)

        await session_store.create(5, "token_5", _make_session_data(5))
        await packet_queue.refresh_ttl(5, _PACKET_QUEUE_TTL)

        # Fire an unrelated event type (just a bare Event)
        await event_bus.fire(Event())

        # User 5 should have no packets
        data = await packet_queue.dequeue_all(5)
        assert data == b""

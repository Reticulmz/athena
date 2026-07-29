"""LifecycleListenersによるUSER_QUIT broadcastとwire packet契約を検証する."""

from __future__ import annotations

import struct
import typing

import pytest

from osu_server.domain.events.users import UserDisconnected
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue  # noqa: TC001
from osu_server.services.queries.identity import (
    ListActiveSessionsQuery,
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.transports.stable.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.writer import write_packet

BANCHO_PACKET_HEADER_SIZE = 7


def _snapshot(user_id: int) -> OnlineSessionSnapshot:
    """Active session query用の最小snapshotを生成する.

    Args:
        user_id (int): 生成するonline userの識別子.

    Returns:
        OnlineSessionSnapshot: USER_QUIT配送先を表す固定値のsnapshot.
    """
    return OnlineSessionSnapshot(
        user_id=user_id,
        username=f"user_{user_id}",
        privileges=0,
        country="JP",
        utc_offset=9,
    )


class FakeListActiveSessionsQuery:
    """指定したuser ID群をonline sessionとして返すquery fakeを表す.

    Attributes:
        user_ids (list[int]): execute時にsnapshotへ変換するonline user ID群.
    """

    def __init__(self) -> None:
        """空のonline user群でquery fakeを初期化する."""
        self.user_ids: list[int] = []

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        """現在のuser ID群をactive session query結果として返す.

        Args:
            input_data (ListActiveSessionsQueryInput): listenerから渡されるquery条件.

        Returns:
            ListActiveSessionsQueryResult: user_idsから生成したsession snapshot群.
        """
        _ = input_data
        return ListActiveSessionsQueryResult(
            sessions=tuple(_snapshot(user_id) for user_id in self.user_ids),
        )


class FakePacketQueue:
    """enqueue要求を順序付きで保持するpacket queue fakeを表す.

    Attributes:
        enqueued (list[tuple[int, bytes]]): user IDとpacket bytesの配送記録.
    """

    def __init__(self) -> None:
        """空の配送記録でpacket queue fakeを初期化する."""
        self.enqueued: list[tuple[int, bytes]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """渡されたpacketを各配送先とともに記録する.

        Args:
            user_id (int): packetを配送するonline userの識別子.
            *data (bytes): 配送順に記録するS2C packet bytes.

        Returns:
            None: 配送記録を追加して完了し,呼び出し側へ値を返さない.
        """
        for packet in data:
            self.enqueued.append((user_id, packet))


@pytest.fixture
def online_users() -> FakeListActiveSessionsQuery:
    """Online userをtestごとに設定できるquery fakeを提供する.

    Returns:
        FakeListActiveSessionsQuery: 初期状態が空の独立したquery fake.
    """
    return FakeListActiveSessionsQuery()


@pytest.fixture
def packet_queue() -> FakePacketQueue:
    """USER_QUIT配送を観測する独立したpacket queue fakeを提供する.

    Returns:
        FakePacketQueue: 初期状態が空の配送記録fake.
    """
    return FakePacketQueue()


@pytest.fixture
def listeners(
    online_users: FakeListActiveSessionsQuery,
    packet_queue: FakePacketQueue,
) -> LifecycleListeners:
    """fake依存を接続したLifecycleListenersを提供する.

    Args:
        online_users (FakeListActiveSessionsQuery): online sessionを返すquery fake.
        packet_queue (FakePacketQueue): 配送packetを記録するqueue fake.

    Returns:
        LifecycleListeners: USER_QUIT broadcastを単独検証できるlistener.
    """
    return LifecycleListeners(
        active_sessions_query=typing.cast(
            "ListActiveSessionsQuery", typing.cast("object", online_users)
        ),  # FakeListActiveSessionsQuery structurally compatible
        packet_queue=typing.cast(
            "PacketQueue", typing.cast("object", packet_queue)
        ),  # FakePacketQueue structurally compatible
    )


def _expected_user_quit_packet(user_id: int) -> bytes:
    """指定userの期待USER_QUIT S2C packetを生成する.

    Args:
        user_id (int): packet payloadへlittle-endian int32で入れるuser ID.

    Returns:
        bytes: protocol writerで構築した完全なUSER_QUIT packet.
    """
    return write_packet(ServerPacketID.USER_QUIT, struct.pack("<i", user_id))


class TestUserQuitBroadcast:
    """disconnect時のUSER_QUIT配送先選択を検証する."""

    async def test_all_online_users_receive_user_quit(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """onlineの他user全員へUSER_QUITを配送する契約を検証する.

        disconnecting userを含むonline user群でlistenerを実行する.
        本人以外の各userが同一USER_QUIT packetを受信することを確認する.

        Args:
            listeners (LifecycleListeners): USER_QUITを配送する対象listener.
            online_users (FakeListActiveSessionsQuery): 本人を含むonline user群を提供するfake.
            packet_queue (FakePacketQueue): 配送結果を観測するqueue fake.

        Returns:
            None: 全配送先を検証して完了し,呼び出し側へ値を返さない.
        """
        disconnecting_user_id = 100
        online_users.user_ids = [1, 2, 3, 100]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        assert (1, expected_packet) in packet_queue.enqueued
        assert (2, expected_packet) in packet_queue.enqueued
        assert (3, expected_packet) in packet_queue.enqueued
        assert len(packet_queue.enqueued) == 3

    async def test_disconnecting_user_excluded_from_broadcast(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Disconnecting user自身をUSER_QUIT配送先から除外する契約を検証する.

        本人と別userがonlineの状態でlistenerを実行し,本人にはpacketがなく別userだけが受信することを確認する.

        Args:
            listeners (LifecycleListeners): USER_QUITを配送する対象listener.
            online_users (FakeListActiveSessionsQuery): 本人と他userを返すquery fake.
            packet_queue (FakePacketQueue): 配送結果を観測するqueue fake.

        Returns:
            None: 自己配送の除外を検証して完了し,呼び出し側へ値を返さない.
        """
        disconnecting_user_id = 42
        online_users.user_ids = [42, 99]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        assert (42, expected_packet) not in packet_queue.enqueued
        assert (99, expected_packet) in packet_queue.enqueued
        assert len(packet_queue.enqueued) == 1

    async def test_no_online_users_completes_without_error(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Online userがいない場合に配送せず正常完了する契約を検証する.

        空のonline user群でdisconnect eventを処理する.
        例外なくqueueへのenqueueが0件となることを確認する.

        Args:
            listeners (LifecycleListeners): 空のsession結果を処理するlistener.
            online_users (FakeListActiveSessionsQuery): 空のonline user群を返すquery fake.
            packet_queue (FakePacketQueue): enqueue件数を観測するqueue fake.

        Returns:
            None: 空群の無配送を検証して完了し,呼び出し側へ値を返さない.
        """
        online_users.user_ids = []

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=1),
        )

        assert len(packet_queue.enqueued) == 0

    async def test_only_disconnecting_user_online_no_enqueue(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Online userがdisconnecting userだけなら配送しない契約を検証する.

        本人だけをonlineにした状態でeventを処理し,自己配送を避けてenqueueが0件となることを確認する.

        Args:
            listeners (LifecycleListeners): USER_QUITを配送する対象listener.
            online_users (FakeListActiveSessionsQuery): 本人だけを返すquery fake.
            packet_queue (FakePacketQueue): 配送結果を観測するqueue fake.

        Returns:
            None: 自己だけの場合の無配送を検証して完了し,呼び出し側へ値を返さない.
        """
        online_users.user_ids = [50]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=50),
        )

        assert len(packet_queue.enqueued) == 0


class TestUserQuitPacketFormat:
    """USER_QUIT packetのpayloadと配送順を検証する."""

    async def test_packet_contains_correct_user_id(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """USER_QUIT payloadがdisconnecting user IDのint32 LEである契約を検証する.

        任意のuser IDでlistenerを実行する.
        queueのpacket payloadをunpackして元のIDと一致することを確認する.

        Args:
            listeners (LifecycleListeners): USER_QUIT packetを生成するlistener.
            online_users (FakeListActiveSessionsQuery): 配送先userを返すquery fake.
            packet_queue (FakePacketQueue): 生成packetを観測するqueue fake.

        Returns:
            None: wire payloadを検証して完了し,呼び出し側へ値を返さない.
        """
        disconnecting_user_id = 12345
        online_users.user_ids = [1]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        assert (1, expected_packet) in packet_queue.enqueued

        # Verify the raw payload structure: header + 4-byte int32
        payload = expected_packet[BANCHO_PACKET_HEADER_SIZE:]
        assert struct.unpack("<i", payload)[0] == disconnecting_user_id

    async def test_enqueue_call_order_matches_online_list(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """enqueue呼び出しがonline user一覧の順序を維持する契約を検証する.

        順序付きonline user群でlistenerを実行する.
        queue記録が同順の配送先と同一packetから成ることを確認する.

        Args:
            listeners (LifecycleListeners): USER_QUITを配送する対象listener.
            online_users (FakeListActiveSessionsQuery): 順序を持つonline user群を返すquery fake.
            packet_queue (FakePacketQueue): enqueue順を観測するqueue fake.

        Returns:
            None: 配送順を検証して完了し,呼び出し側へ値を返さない.
        """
        online_users.user_ids = [10, 20, 30]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=99),
        )

        expected_packet = _expected_user_quit_packet(99)
        assert packet_queue.enqueued == [
            (10, expected_packet),
            (20, expected_packet),
            (30, expected_packet),
        ]

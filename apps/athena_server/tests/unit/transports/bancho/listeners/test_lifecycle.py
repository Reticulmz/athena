"""LifecycleListenersのpresenceとUSER_QUIT fan-out contractを検証する."""

from __future__ import annotations

import struct
import typing

import pytest

from osu_server.domain.compatibility.stable.permissions import BanchoClientPermission
from osu_server.domain.events.users import UserConnected, UserDisconnected
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue  # noqa: TC001
from osu_server.infrastructure.state.memory.stable_user_status_store import (
    InMemoryStableUserStatusStore,
)
from osu_server.services.queries.identity import (
    ListActiveSessionsQuery,
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.transports.stable.bancho.listeners.lifecycle import LifecycleListeners
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_presence
from osu_server.transports.stable.bancho.protocol.writer import write_packet


def _snapshot(user_id: int) -> OnlineSessionSnapshot:
    """指定user IDを持つ既定のonline session snapshotを作る.

    Args:
        user_id (int): snapshotへ設定するstable userのID.

    Returns:
        OnlineSessionSnapshot: JP localeと既定privilegeを持つactive session snapshot.
    """
    return OnlineSessionSnapshot(
        user_id=user_id,
        username=f"user_{user_id}",
        privileges=0,
        country="JP",
        utc_offset=9,
    )


class FakeListActiveSessionsQuery:
    """設定した人間user IDだけを返すListActiveSessionsQuery fakeを提供する.

    Attributes:
        user_ids (list[int]): active sessionとして返すuser IDの順序.
    """

    def __init__(self) -> None:
        """BanchoBotを含まない空のactive session一覧を初期化する."""
        self.user_ids: list[int] = []

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        """設定済みuser IDをonline session snapshotへ変換して返す.

        Args:
            input_data (ListActiveSessionsQueryInput): active session取得を表すquery input.

        Returns:
            ListActiveSessionsQueryResult: 設定済みuser IDだけを含むactive session result.
        """
        _ = input_data
        return ListActiveSessionsQueryResult(
            sessions=tuple(_snapshot(user_id) for user_id in self.user_ids),
        )


class FakePacketQueue:
    """enqueueされたrecipientとpacketを記録するPacketQueue fakeを提供する.

    Attributes:
        enqueued (list[tuple[int, bytes]]): recipient user IDとpacketの記録順序.
    """

    def __init__(self) -> None:
        """空のenqueue記録を持つpacket queue fakeを初期化する."""
        self.enqueued: list[tuple[int, bytes]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """recipientごとにS2C packetを記録する.

        Args:
            user_id (int): packetを受け取るonline userのID.
            *data (bytes): queueへ渡されたS2C packet群.

        Returns:
            None: 全packetを記録して完了し, 呼び出し側へ値を返さない.
        """
        for packet in data:
            self.enqueued.append((user_id, packet))


@pytest.fixture
def online_users() -> FakeListActiveSessionsQuery:
    """Active session user IDを設定するquery fakeを提供する.

    Returns:
        FakeListActiveSessionsQuery: active session一覧を記録なしで返すfixture.
    """
    return FakeListActiveSessionsQuery()


@pytest.fixture
def packet_queue() -> FakePacketQueue:
    """fan-out結果を記録するpacket queue fakeを提供する.

    Returns:
        FakePacketQueue: recipientとpacketを順序どおり記録するfixture.
    """
    return FakePacketQueue()


@pytest.fixture
def listeners(
    online_users: FakeListActiveSessionsQuery,
    packet_queue: FakePacketQueue,
) -> LifecycleListeners:
    """Typed fake依存を注入したLifecycleListenersを提供する.

    Args:
        online_users (FakeListActiveSessionsQuery): active session一覧を返すquery fake.
        packet_queue (FakePacketQueue): fan-out結果を記録するqueue fake.

    Returns:
        LifecycleListeners: lifecycle eventをstable packet fan-outへ変換するlistener.
    """
    return LifecycleListeners(
        active_sessions_query=typing.cast(
            "ListActiveSessionsQuery",
            typing.cast("object", online_users),
        ),
        packet_queue=typing.cast("PacketQueue", typing.cast("object", packet_queue)),
    )


def _expected_user_quit_packet(user_id: int) -> bytes:
    """指定userのexpected USER_QUIT S2C packetを構築する.

    Args:
        user_id (int): USER_QUIT payloadへ入れる切断userのID.

    Returns:
        bytes: signed int32 user IDを含むUSER_QUIT packet.
    """
    return write_packet(ServerPacketID.USER_QUIT, struct.pack("<i", user_id))


def _expected_user_presence_packet(
    session: OnlineSessionSnapshot,
    *,
    play_mode: int = 0,
) -> bytes:
    """Online session向けexpected USER_PRESENCE S2C packetを構築する.

    Args:
        session (OnlineSessionSnapshot): presence fieldを提供するactive session snapshot.
        play_mode (int): permissions_modeへ合成するstable play mode.

    Returns:
        bytes: sessionのidentityと既定位置情報を含むUSER_PRESENCE packet.
    """
    return user_presence(
        user_id=session.user_id,
        username=session.username,
        timezone=session.utc_offset + 24,
        country_id=country_code_to_id(session.country),
        permissions=int(BanchoClientPermission.NORMAL),
        mode=play_mode,
        longitude=0.0,
        latitude=0.0,
        rank=0,
    )


class TestUserPresenceBroadcast:
    """UserConnected eventのUSER_PRESENCE fan-outを検証する."""

    async def test_connected_user_presence_broadcasts_to_other_online_users(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """接続userのpresenceを他のactive sessionへfan-outする契約を検証する.

        Args:
            listeners (LifecycleListeners): UserConnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): 接続userを含むactive session query fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: 自身以外のrecipientへ送るexact presence packetを確認して完了する.
        """
        connected_user_id = 20
        online_users.user_ids = [10, connected_user_id, 30]

        await listeners.on_user_connected(UserConnected(user_id=connected_user_id))

        expected_packet = _expected_user_presence_packet(_snapshot(connected_user_id))
        assert packet_queue.enqueued == [
            (10, expected_packet),
            (30, expected_packet),
        ]

    async def test_connected_user_does_not_receive_own_presence_broadcast(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """接続user自身のqueueをlive presence fan-outから除外する契約を検証する.

        Args:
            listeners (LifecycleListeners): UserConnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): 接続userを含むactive session query fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: 自身不在と他recipientだけのtarget一覧を検証して完了し, 呼び出し側へ値を返さない.
        """
        connected_user_id = 42
        online_users.user_ids = [connected_user_id, 99]

        await listeners.on_user_connected(UserConnected(user_id=connected_user_id))

        target_ids = [uid for uid, _ in packet_queue.enqueued]
        assert connected_user_id not in target_ids
        assert target_ids == [99]

    async def test_connected_user_presence_uses_current_mode(
        self,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """UserConnected fan-outが保存済みcurrent modeをUSER_PRESENCEへ載せる契約を検証する.

        Args:
            online_users (FakeListActiveSessionsQuery): 接続userを含むactive session query fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: current modeを含むexact presence packetを確認して完了する.
        """
        connected_user_id = 20
        status_store = InMemoryStableUserStatusStore()
        await status_store.set_play_mode(connected_user_id, 3)
        listeners = LifecycleListeners(
            active_sessions_query=typing.cast(
                "ListActiveSessionsQuery",
                typing.cast("object", online_users),
            ),
            packet_queue=typing.cast("PacketQueue", typing.cast("object", packet_queue)),
            stable_user_status_store=status_store,
        )
        online_users.user_ids = [10, connected_user_id, 30]

        await listeners.on_user_connected(UserConnected(user_id=connected_user_id))

        expected_packet = _expected_user_presence_packet(
            _snapshot(connected_user_id),
            play_mode=3,
        )
        assert packet_queue.enqueued == [
            (10, expected_packet),
            (30, expected_packet),
        ]

    async def test_connected_event_without_active_session_is_noop(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """接続userのactive sessionがない場合にpresenceを送らない契約を検証する.

        Args:
            listeners (LifecycleListeners): UserConnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): 接続userを欠くactive session query fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: queueが空のままであることを検証して完了し, 呼び出し側へ値を返さない.
        """
        online_users.user_ids = [10, 30]

        await listeners.on_user_connected(UserConnected(user_id=20))

        assert packet_queue.enqueued == []

    async def test_only_connected_user_online_no_presence_broadcast(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """接続userだけがonlineの場合にpresence fan-outを行わない契約を検証する.

        Args:
            listeners (LifecycleListeners): UserConnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): 接続userだけを返すactive session
                query fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: queueが空のままであることを検証して完了し, 呼び出し側へ値を返さない.
        """
        online_users.user_ids = [20]

        await listeners.on_user_connected(UserConnected(user_id=20))

        assert packet_queue.enqueued == []


class TestBanchoBotNotInUserQuitFanOut:
    """USER_QUIT fan-outがBanchoBotをrecipientにしないcontractを検証する.

    Notes:
        LifecycleListenersはactive SessionDataを返すqueryだけをrecipient sourceとして使う.
    """

    async def test_banchobot_not_in_fanout_with_multiple_users(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """複数humanがonlineでもBanchoBotをUSER_QUIT recipientにしない契約を検証する.

        Args:
            listeners (LifecycleListeners): UserDisconnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): 複数human active sessionを返すquery fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: BanchoBot不在とhuman recipient集合を検証して完了し, 呼び出し側へ値を返さない.
        """
        disconnecting_user_id = 100
        # Active session IDs — BanchoBot (user_id=1) is not a session
        online_users.user_ids = [2, 3, 42, 100]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        target_ids = [uid for uid, _ in packet_queue.enqueued]
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids
        # Only human users excluding the disconnecting one
        assert set(target_ids) == {2, 3, 42}
        assert len(packet_queue.enqueued) == 3

    async def test_banchobot_not_in_fanout_with_single_user(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """他humanが1人だけでもBanchoBotをUSER_QUIT recipientにしない契約を検証する.

        Args:
            listeners (LifecycleListeners): UserDisconnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): 切断userと他humanを返すquery fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: 唯一のhuman recipientだけを検証して完了し, 呼び出し側へ値を返さない.
        """
        disconnecting_user_id = 50
        online_users.user_ids = [50, 99]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        target_ids = [uid for uid, _ in packet_queue.enqueued]
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids
        assert target_ids == [99]
        assert len(packet_queue.enqueued) == 1

    async def test_banchobot_not_in_fanout_no_other_users(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """切断userだけがonlineの場合にUSER_QUIT fan-outを行わない契約を検証する.

        Args:
            listeners (LifecycleListeners): UserDisconnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): 切断userだけを返すquery fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: BanchoBot不在と空queueを検証して完了し, 呼び出し側へ値を返さない.
        """
        online_users.user_ids = [50]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=50),
        )

        target_ids = [uid for uid, _ in packet_queue.enqueued]
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids
        assert len(packet_queue.enqueued) == 0

    async def test_banchobot_exclusion_preserves_user_quit_packet_format(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Human recipientへ送るUSER_QUITがsigned int32 user ID formatを保つ契約を検証する.

        Args:
            listeners (LifecycleListeners): UserDisconnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): human recipientを返すquery fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: exact USER_QUIT packetとBanchoBot不在を検証して完了し, 呼び出し側へ値を返さない.
        """
        disconnecting_user_id = 77
        online_users.user_ids = [2, 77]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=disconnecting_user_id),
        )

        expected_packet = _expected_user_quit_packet(disconnecting_user_id)
        assert packet_queue.enqueued == [(2, expected_packet)]
        # No entry for BanchoBot
        assert BANCHO_BOT_IDENTITY.user_id not in [uid for uid, _ in packet_queue.enqueued]


class TestBanchoBotSessionSeparationContract:
    """BanchoBot roster identityとactive session sourceの分離contractを検証する.

    Notes:
        Lifecycle fan-outはListActiveSessionsQueryのresultだけをrecipient sourceとして使う.
    """

    async def test_fan_out_uses_active_session_query_exclusively(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """LifecycleListenersがactive session query resultだけへfan-outする契約を検証する.

        Args:
            listeners (LifecycleListeners): UserDisconnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): human active sessionを返すquery fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: query由来recipientとBanchoBot不在を検証して完了し, 呼び出し側へ値を返さない.
        """
        online_users.user_ids = [10, 20, 30]

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=10),
        )

        # All enqueued targets come from ListActiveSessionsQuery
        target_ids = {uid for uid, _ in packet_queue.enqueued}
        assert target_ids == {20, 30}
        assert BANCHO_BOT_IDENTITY.user_id not in target_ids

    async def test_no_banchobot_leakage_from_empty_online_list(
        self,
        listeners: LifecycleListeners,
        online_users: FakeListActiveSessionsQuery,
        packet_queue: FakePacketQueue,
    ) -> None:
        """Online userがない場合にBanchoBotを追加せずfan-outを行わない契約を検証する.

        Args:
            listeners (LifecycleListeners): UserDisconnected eventを処理するlistener fixture.
            online_users (FakeListActiveSessionsQuery): 空のactive sessionを返すquery fake.
            packet_queue (FakePacketQueue): fan-out結果を記録するqueue fixture.

        Returns:
            None: 空queueとBanchoBot不在を検証して完了し, 呼び出し側へ値を返さない.
        """
        online_users.user_ids = []

        await listeners.on_user_disconnected(
            UserDisconnected(user_id=42),
        )

        assert len(packet_queue.enqueued) == 0
        # Even in empty state, BanchoBot is never enqueued
        assert BANCHO_BOT_IDENTITY.user_id not in [uid for uid, _ in packet_queue.enqueued]

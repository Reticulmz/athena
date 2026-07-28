"""Bancho presence handlerがonline sessionとplay modeをpacketへ反映することを検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.state.memory.stable_user_status_store import (
    InMemoryStableUserStatusStore,
)
from osu_server.services.queries.identity import (
    GetActiveSessionsByUserIdsQuery,
    GetActiveSessionsByUserIdsQueryInput,
    GetActiveSessionsByUserIdsQueryResult,
    ListActiveSessionsQuery,
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.transports.stable.bancho.handlers.presence import PresenceHandlers
from osu_server.transports.stable.bancho.mappers.presence import (
    bot_presence_packet,
    online_session_presence_packet,
    online_session_presence_packet_for_mode,
)
from osu_server.transports.stable.bancho.protocol.c2s import presence_request_payload
from osu_server.transports.stable.bancho.protocol.s2c.login import user_presence_bundle

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue


@final
class FakeListActiveSessionsQuery:
    """全online sessionを固定結果として返すquery fake.

    Attributes:
        calls (int): executeが呼ばれた回数.
    """

    def __init__(self, sessions: tuple[OnlineSessionSnapshot, ...]) -> None:
        """返却するonline sessionを固定する.

        Args:
            sessions (tuple[OnlineSessionSnapshot, ...]): 全件requestで返すsession snapshot.
        """
        self._sessions = sessions
        self.calls = 0

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        """入力型を確認して固定session一覧を返す.

        Args:
            input_data (ListActiveSessionsQueryInput): handlerが構築した全session検索input.

        Returns:
            ListActiveSessionsQueryResult: 初期化時のsessionを保持するquery result.

        Raises:
            AssertionError: inputがquery contractの型でない場合.
        """
        assert isinstance(input_data, ListActiveSessionsQueryInput)
        self.calls += 1
        return ListActiveSessionsQueryResult(sessions=self._sessions)


@final
class FakeGetActiveSessionsByUserIdsQuery:
    """指定user IDに一致するonline sessionを固定結果から返すquery fake.

    Attributes:
        inputs (list[tuple[int, ...]]): executeへ渡されたuser ID群の呼出順list.
    """

    def __init__(self, sessions: tuple[OnlineSessionSnapshot, ...]) -> None:
        """User IDで検索できる固定session snapshotを登録する.

        Args:
            sessions (tuple[OnlineSessionSnapshot, ...]): ID検索の候補にするsession snapshot.
        """
        self._sessions_by_user_id = {session.user_id: session for session in sessions}
        self.inputs: list[tuple[int, ...]] = []

    async def execute(
        self,
        input_data: GetActiveSessionsByUserIdsQueryInput,
    ) -> GetActiveSessionsByUserIdsQueryResult:
        """入力順に存在するsessionだけを返す.

        Args:
            input_data (GetActiveSessionsByUserIdsQueryInput): handlerが構築したuser ID検索input.

        Returns:
            GetActiveSessionsByUserIdsQueryResult: 要求IDに対応する既知sessionだけを含むresult.

        Raises:
            AssertionError: inputがquery contractの型でない場合.
        """
        assert isinstance(input_data, GetActiveSessionsByUserIdsQueryInput)
        self.inputs.append(input_data.user_ids)
        return GetActiveSessionsByUserIdsQueryResult(
            sessions=tuple(
                self._sessions_by_user_id[user_id]
                for user_id in input_data.user_ids
                if user_id in self._sessions_by_user_id
            )
        )


@final
class FakePacketQueue:
    """enqueueしたstable packetを記録するPacketQueue fake.

    Attributes:
        enqueued (list[tuple[int, tuple[bytes, ...]]]): 宛先user IDとpacket群の呼出順list.
    """

    def __init__(self) -> None:
        """空のenqueue記録を持つfakeを初期化する."""
        self.enqueued: list[tuple[int, tuple[bytes, ...]]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """宛先とpacket群を記録する.

        Args:
            user_id (int): packetを配送するstable user ID.
            *data (bytes): 配送順を保って記録するserialized packet.

        Returns:
            None: enqueue記録を追加して完了する.
        """
        self.enqueued.append((user_id, data))

    async def dequeue_all(self, user_id: int) -> bytes:
        """Protocol互換の空queue読出し結果を返す.

        Args:
            user_id (int): 読出し対象のstable user ID. fakeでは使用しない.

        Returns:
            bytes: 常に空bytes. このtestはenqueue記録だけを観測する.
        """
        _ = user_id
        return b""

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """Protocol互換のTTL更新要求を受け入れる.

        Args:
            user_id (int): TTL更新対象のstable user ID. fakeでは使用しない.
            ttl (int): 更新後TTL秒数. fakeでは使用しない.

        Returns:
            None: 状態を変更せずTTL要求を受理して完了する.
        """
        _ = (user_id, ttl)


async def test_presence_request_returns_requested_online_user_presence() -> None:
    """Presence requestが要求順のonline userとBanchoBotだけを返すことを検証する.

    Returns:
        None: offline userを除外したpresence packetとID検索inputを確認して完了する.
    """
    online = (_snapshot(20), _snapshot(30))
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
    )

    await handlers.handle_presence_request(
        presence_request_payload([30, BANCHO_BOT_IDENTITY.user_id, 20, 99]),
        user_id=3,
    )

    assert packet_queue.enqueued == [
        (
            3,
            (
                online_session_presence_packet(online[1]),
                bot_presence_packet(),
                online_session_presence_packet(online[0]),
            ),
        )
    ]
    assert active_sessions_query.calls == 0
    assert active_sessions_by_user_ids_query.inputs == [(30, 20, 99)]


async def test_presence_request_drops_malformed_payload_without_enqueue() -> None:
    """Malformed presence requestがpacketをenqueueしないことを検証する.

    Returns:
        None: queue記録が空であることを確認して完了する.
    """
    packet_queue = FakePacketQueue()
    handlers = _handlers(
        FakeListActiveSessionsQuery((_snapshot(20),)),
        FakeGetActiveSessionsByUserIdsQuery((_snapshot(20),)),
        packet_queue,
    )

    await handlers.handle_presence_request(b"\x00", user_id=3)

    assert packet_queue.enqueued == []


async def test_presence_request_all_accepts_bancho_py_reserved_int32_payload() -> None:
    """Reserved int32 payloadのpresence all requestがroster bundleを返すことを検証する.

    Returns:
        None: botとonline userのpresence packetおよびuser presence bundleを確認して完了する.
    """
    online = (_snapshot(20), _snapshot(30))
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
    )

    await handlers.handle_presence_request_all(b"\x00\x00\x00\x00", user_id=3)

    assert packet_queue.enqueued == [
        (
            3,
            (
                bot_presence_packet(),
                online_session_presence_packet(online[0]),
                online_session_presence_packet(online[1]),
                user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 20, 30]),
            ),
        )
    ]
    assert active_sessions_query.calls == 1
    assert active_sessions_by_user_ids_query.inputs == []


async def test_presence_request_uses_target_user_current_mode() -> None:
    """Individual presence requestがtarget userの現在play modeを使うことを検証する.

    Returns:
        None: targetだけが保存済みplay modeでserializeされることを確認して完了する.
    """
    online = (_snapshot(20), _snapshot(30))
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_play_mode(20, 3)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
        stable_user_status_store=status_store,
    )

    await handlers.handle_presence_request(
        presence_request_payload([20, 30]),
        user_id=3,
    )

    assert packet_queue.enqueued == [
        (
            3,
            (
                online_session_presence_packet_for_mode(online[0], play_mode=3),
                online_session_presence_packet(online[1]),
            ),
        )
    ]
    assert active_sessions_query.calls == 0
    assert active_sessions_by_user_ids_query.inputs == [(20, 30)]


async def test_presence_request_uses_requester_current_mode_for_bot() -> None:
    """Bot presenceがrequesterの現在play modeを使うことを検証する.

    Returns:
        None: bot packetがrequesterの保存済みplay modeを持つことを確認して完了する.
    """
    online = (_snapshot(20),)
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_play_mode(3, 3)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
        stable_user_status_store=status_store,
    )

    await handlers.handle_presence_request(
        presence_request_payload([BANCHO_BOT_IDENTITY.user_id]),
        user_id=3,
    )

    assert packet_queue.enqueued == [
        (
            3,
            (bot_presence_packet(play_mode=3),),
        )
    ]
    assert active_sessions_query.calls == 0
    assert active_sessions_by_user_ids_query.inputs == [()]


async def test_presence_request_all_uses_target_user_current_modes_for_roster() -> None:
    """Presence all rosterが各target userの現在play modeを使うことを検証する.

    Returns:
        None: target packetだけが保存済みplay modeでserializeされることを確認して完了する.
    """
    online = (_snapshot(20), _snapshot(30))
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_play_mode(20, 3)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
        stable_user_status_store=status_store,
    )

    await handlers.handle_presence_request_all(b"\x00\x00\x00\x00", user_id=3)

    assert packet_queue.enqueued == [
        (
            3,
            (
                bot_presence_packet(),
                online_session_presence_packet_for_mode(online[0], play_mode=3),
                online_session_presence_packet(online[1]),
                user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 20, 30]),
            ),
        )
    ]
    assert active_sessions_query.calls == 1
    assert active_sessions_by_user_ids_query.inputs == []


async def test_presence_request_all_uses_requester_current_mode_for_bot() -> None:
    """Presence all requestのbot packetがrequesterの現在play modeを使うことを検証する.

    Returns:
        None: bot packetがrequesterの保存済みplay modeを持つことを確認して完了する.
    """
    online = (_snapshot(20),)
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeListActiveSessionsQuery(online)
    active_sessions_by_user_ids_query = FakeGetActiveSessionsByUserIdsQuery(online)
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_play_mode(3, 3)
    handlers = _handlers(
        active_sessions_query,
        active_sessions_by_user_ids_query,
        packet_queue,
        stable_user_status_store=status_store,
    )

    await handlers.handle_presence_request_all(b"\x00\x00\x00\x00", user_id=3)

    assert packet_queue.enqueued == [
        (
            3,
            (
                bot_presence_packet(play_mode=3),
                online_session_presence_packet(online[0]),
                user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 20]),
            ),
        )
    ]
    assert active_sessions_query.calls == 1
    assert active_sessions_by_user_ids_query.inputs == []


async def test_presence_request_all_drops_unknown_payload_size() -> None:
    """不正なpayload sizeのpresence all requestがpacketをenqueueしないことを検証する.

    Returns:
        None: queue記録が空であることを確認して完了する.
    """
    packet_queue = FakePacketQueue()
    handlers = _handlers(
        FakeListActiveSessionsQuery((_snapshot(20),)),
        FakeGetActiveSessionsByUserIdsQuery((_snapshot(20),)),
        packet_queue,
    )

    await handlers.handle_presence_request_all(b"\x00", user_id=3)

    assert packet_queue.enqueued == []


def _handlers(
    active_sessions_query: FakeListActiveSessionsQuery,
    active_sessions_by_user_ids_query: FakeGetActiveSessionsByUserIdsQuery,
    packet_queue: FakePacketQueue,
    *,
    stable_user_status_store: InMemoryStableUserStatusStore | None = None,
) -> PresenceHandlers:
    """指定fakeを注入したPresenceHandlersを構築する.

    Args:
        active_sessions_query (FakeListActiveSessionsQuery): 全online sessionを返すquery fake.
        active_sessions_by_user_ids_query (FakeGetActiveSessionsByUserIdsQuery):
            ID検索用query fake.
        packet_queue (FakePacketQueue): enqueue内容を記録するqueue fake.
        stable_user_status_store (InMemoryStableUserStatusStore | None):
            Play mode参照用store. None時はhandler既定値を使う.

    Returns:
        PresenceHandlers: stable protocol用dependencyを持つhandler集合.
    """
    return PresenceHandlers(
        active_sessions_query=cast(
            "ListActiveSessionsQuery",
            active_sessions_query,
        ),
        active_sessions_by_user_ids_query=cast(
            "GetActiveSessionsByUserIdsQuery",
            active_sessions_by_user_ids_query,
        ),
        packet_queue=cast("PacketQueue", packet_queue),
        stable_user_status_store=stable_user_status_store,
    )


def _snapshot(
    user_id: int,
    *,
    username: str | None = None,
    privileges: int = 0,
) -> OnlineSessionSnapshot:
    """Presence packet用のonline session snapshotを構築する.

    Args:
        user_id (int): snapshotへ設定するstable user ID.
        username (str | None): 表示名. None時はuser IDから生成する.
        privileges (int): snapshotへ設定するstable privilege bitmask.

    Returns:
        OnlineSessionSnapshot: 日本のUTC+9 sessionとして初期化したsnapshot.
    """
    return OnlineSessionSnapshot(
        user_id=user_id,
        username=username or f"user_{user_id}",
        privileges=privileges,
        country="JP",
        utc_offset=9,
    )

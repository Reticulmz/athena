"""Bancho stats request handlerがsession可視性とcurrent statusを反映することを検証する."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, cast, final

from osu_server.domain.compatibility.stable import (
    DEFAULT_STABLE_USER_STATUS,
    StableUserStatus,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserCurrentStats
from osu_server.services.queries.identity import (
    GetActiveSessionsByUserIdsQueryInput,
    GetActiveSessionsByUserIdsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.services.queries.scores import (
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
)
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.stats import StatsRequestHandler
from osu_server.transports.stable.bancho.mappers.user_stats import bot_user_stats_packet
from osu_server.transports.stable.bancho.protocol.c2s import stats_request_payload
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.identity import GetActiveSessionsByUserIdsQuery
    from osu_server.services.queries.scores import CurrentUserStatsQuery


@final
class FakeCurrentUserStatsQuery:
    """固定のcurrent user statsを返すquery fake.

    Attributes:
        inputs (list[CurrentUserStatsQueryInput]): executeへ渡された検索inputの呼出順list.
    """

    def __init__(
        self,
        *,
        stats: tuple[UserCurrentStats, ...] = (),
        stats_by_ruleset: dict[Ruleset, tuple[UserCurrentStats, ...]] | None = None,
        error: Exception | None = None,
    ) -> None:
        """固定resultまたは読出し失敗を設定する.

        Args:
            stats (tuple[UserCurrentStats, ...]): ruleset未指定時に返すstats.
            stats_by_ruleset (dict[Ruleset, tuple[UserCurrentStats, ...]] | None):
                Ruleset別の返却値.
            error (Exception | None): execute時に送出する読出し失敗. None時は送出しない.
        """
        self._stats = stats
        self._stats_by_ruleset = stats_by_ruleset or {}
        self._error = error
        self.inputs: list[CurrentUserStatsQueryInput] = []

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """検索inputを記録して対応する固定statsを返す.

        Args:
            input_data (CurrentUserStatsQueryInput): handlerが構築したstats検索input.

        Returns:
            CurrentUserStatsQueryResult: 指定rulesetまたは既定値のstatsを持つresult.

        Raises:
            Exception: 初期化時に設定されたerrorが存在する場合.
        """
        self.inputs.append(input_data)
        if self._error is not None:
            raise self._error
        if self._stats_by_ruleset:
            return CurrentUserStatsQueryResult(
                stats=self._stats_by_ruleset.get(input_data.ruleset, ())
            )
        return CurrentUserStatsQueryResult(stats=self._stats)


@final
class FakePacketQueue:
    """enqueueしたstable stats packetを記録するPacketQueue fake.

    Attributes:
        enqueued (list[tuple[int, tuple[bytes, ...]]]): 宛先user IDとpacket群の呼出順list.
    """

    def __init__(self) -> None:
        """空のenqueue記録を持つfakeを初期化する."""
        self.enqueued: list[tuple[int, tuple[bytes, ...]]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """宛先とserialized packetを記録する.

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
            user_id (int): 読出し対象user ID. fakeでは使用しない.

        Returns:
            bytes: 常に空bytes. このtestはenqueue記録だけを観測する.
        """
        _ = user_id
        return b""

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """Protocol互換のTTL更新要求を受け入れる.

        Args:
            user_id (int): TTL更新対象user ID. fakeでは使用しない.
            ttl (int): 更新後TTL秒数. fakeでは使用しない.

        Returns:
            None: 状態を変更せずTTL要求を受理して完了する.
        """
        _ = (user_id, ttl)


@final
class FakeStableUserStatusStore:
    """Current statusとplay modeをin-memoryで保持するstore fake.

    Attributes:
        refreshed (list[tuple[int, int]]): refresh_ttlへ渡されたuser IDとTTL秒数の呼出順list.
    """

    def __init__(
        self,
        play_modes: dict[int, int] | None = None,
        statuses: dict[int, StableUserStatus] | None = None,
    ) -> None:
        """初期statusまたはplay modeからstore状態を構築する.

        Args:
            play_modes (dict[int, int] | None): user IDごとの初期play mode. status未指定時に使う.
            statuses (dict[int, StableUserStatus] | None): user IDごとの初期stable status.
        """
        self._statuses = statuses or {
            user_id: DEFAULT_STABLE_USER_STATUS.with_play_mode(mode)
            for user_id, mode in (play_modes or {}).items()
        }
        self.refreshed: list[tuple[int, int]] = []

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """指定userのcurrent stable statusを保存する.

        Args:
            user_id (int): 更新対象のstable user ID.
            status (StableUserStatus): 保存するcurrent statusとplay mode.

        Returns:
            None: statusをin-memory状態へ反映して完了する.
        """
        self._statuses[user_id] = status

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """要求IDに存在するcurrent statusだけを返す.

        Args:
            user_ids (tuple[int, ...]): statusを取得するstable user ID群.

        Returns:
            dict[int, StableUserStatus]: 既知userだけを含むstatus mapping.
        """
        return {
            user_id: status
            for user_id in user_ids
            if (status := self._statuses.get(user_id)) is not None
        }

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        """指定userのplay modeを現在statusへ反映する.

        Args:
            user_id (int): 更新対象のstable user ID.
            play_mode (int): 保存するstable play mode値.

        Returns:
            None: 既存statusまたは既定statusへplay modeを反映して完了する.
        """
        current = self._statuses.get(user_id, DEFAULT_STABLE_USER_STATUS)
        self._statuses[user_id] = current.with_play_mode(play_mode)

    async def get_play_mode(self, user_id: int) -> int | None:
        """指定userのplay modeを返す.

        Args:
            user_id (int): play modeを取得するstable user ID.

        Returns:
            int | None: 既知userのplay mode. 未登録時はNone.
        """
        status = self._statuses.get(user_id)
        return None if status is None else status.play_mode

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """要求IDに存在するplay modeだけを返す.

        Args:
            user_ids (tuple[int, ...]): play modeを取得するstable user ID群.

        Returns:
            dict[int, int]: 既知userだけを含むplay mode mapping.
        """
        return {
            user_id: status.play_mode
            for user_id in user_ids
            if (status := self._statuses.get(user_id)) is not None
        }

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """TTL更新要求を記録する.

        Args:
            user_id (int): TTL更新対象のstable user ID.
            ttl (int): 更新後TTL秒数.

        Returns:
            None: user IDとTTL秒数の組を記録して完了する.
        """
        self.refreshed.append((user_id, ttl))


@final
class FakeActiveSessionsByUserIdsQuery:
    """指定user IDに一致するonline sessionを返すquery fake.

    Attributes:
        inputs (list[GetActiveSessionsByUserIdsQueryInput]): executeへ渡された検索inputの
            呼出順list.
    """

    def __init__(self, sessions: tuple[OnlineSessionSnapshot, ...]) -> None:
        """ID検索の候補にするonline sessionを固定する.

        Args:
            sessions (tuple[OnlineSessionSnapshot, ...]): 既知online session snapshot.
        """
        self._sessions = sessions
        self.inputs: list[GetActiveSessionsByUserIdsQueryInput] = []

    async def execute(
        self,
        input_data: GetActiveSessionsByUserIdsQueryInput,
    ) -> GetActiveSessionsByUserIdsQueryResult:
        """検索inputを記録して一致するsessionだけを返す.

        Args:
            input_data (GetActiveSessionsByUserIdsQueryInput): handlerが構築したsession検索input.

        Returns:
            GetActiveSessionsByUserIdsQueryResult: 要求IDに一致するonline sessionを持つresult.
        """
        self.inputs.append(input_data)
        requested = set(input_data.user_ids)
        return GetActiveSessionsByUserIdsQueryResult(
            sessions=tuple(session for session in self._sessions if session.user_id in requested)
        )


async def test_stats_request_returns_current_stats_for_available_users() -> None:
    """Available userのcurrent statsをstable packetへ変換することを検証する.

    Returns:
        None: query inputとserialized user stats packetを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(
        stats=(
            UserCurrentStats(
                user_id=20,
                pp=Decimal("122.5"),
                accuracy=0.9876,
                global_rank=12,
                play_count=34,
                ranked_score=123_456_789,
                total_score=9_876_543_210,
            ),
        )
    )
    packet_queue = FakePacketQueue()
    handler = _handler(stats_query, packet_queue)

    await handler.handle_stats_request(stats_request_payload([20, 99]), user_id=3)

    assert stats_query.inputs == [CurrentUserStatsQueryInput(user_ids=(20, 99))]
    assert packet_queue.enqueued == [
        (
            3,
            (
                user_stats(
                    user_id=20,
                    status=0,
                    status_text="",
                    beatmap_md5="",
                    mods=0,
                    play_mode=0,
                    beatmap_id=0,
                    ranked_score=123_456_789,
                    accuracy=0.9876,
                    play_count=34,
                    total_score=9_876_543_210,
                    rank=12,
                    pp=123,
                ),
            ),
        )
    ]


async def test_stats_request_deduplicates_requested_user_ids() -> None:
    """重複したrequested user IDを一度だけ検索してpacket化することを検証する.

    Returns:
        None: 重複なしquery inputとuserごとに1件のpacketを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(
        stats=(
            UserCurrentStats(user_id=20, pp=Decimal("50"), global_rank=2),
            UserCurrentStats(user_id=30, pp=Decimal("25"), global_rank=3),
        )
    )
    packet_queue = FakePacketQueue()
    handler = _handler(stats_query, packet_queue)

    await handler.handle_stats_request(stats_request_payload([20, 20, 30]), user_id=3)

    assert stats_query.inputs == [CurrentUserStatsQueryInput(user_ids=(20, 30))]
    assert packet_queue.enqueued == [
        (
            3,
            (
                user_stats(
                    user_id=20,
                    status=0,
                    status_text="",
                    beatmap_md5="",
                    mods=0,
                    play_mode=0,
                    beatmap_id=0,
                    ranked_score=0,
                    accuracy=0.0,
                    play_count=0,
                    total_score=0,
                    rank=2,
                    pp=50,
                ),
                user_stats(
                    user_id=30,
                    status=0,
                    status_text="",
                    beatmap_md5="",
                    mods=0,
                    play_mode=0,
                    beatmap_id=0,
                    ranked_score=0,
                    accuracy=0.0,
                    play_count=0,
                    total_score=0,
                    rank=3,
                    pp=25,
                ),
            ),
        )
    ]


async def test_stats_request_omits_unavailable_users_without_default_packet() -> None:
    """Statsが存在しないuserに既定packetを返さないことを検証する.

    Returns:
        None: unavailable userのquery実行後もqueue記録が空であることを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(stats=())
    packet_queue = FakePacketQueue()
    handler = _handler(stats_query, packet_queue)

    await handler.handle_stats_request(stats_request_payload([99]), user_id=3)

    assert stats_query.inputs == [CurrentUserStatsQueryInput(user_ids=(99,))]
    assert packet_queue.enqueued == []


async def test_stats_request_drops_malformed_payload_without_enqueue() -> None:
    """Malformed stats request payloadがqueryもpacket配送も行わないことを検証する.

    Returns:
        None: query inputとqueue記録がともに空であることを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(
        stats=(UserCurrentStats(user_id=20, pp=Decimal("50"), global_rank=2),)
    )
    packet_queue = FakePacketQueue()
    handler = _handler(stats_query, packet_queue)

    await handler.handle_stats_request(b"\x01", user_id=3)

    assert stats_query.inputs == []
    assert packet_queue.enqueued == []


async def test_stats_request_uses_target_user_current_play_mode() -> None:
    """Target userのcurrent play modeでruleset別statsを検索することを検証する.

    Returns:
        None: targetのplay modeに対応するquery inputとstats packetを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(
        stats_by_ruleset={
            Ruleset.MANIA: (
                UserCurrentStats(
                    user_id=20,
                    pp=Decimal("250"),
                    accuracy=0.99,
                    global_rank=1,
                    play_count=5,
                    ranked_score=900_000,
                    total_score=900_000,
                ),
            ),
        }
    )
    packet_queue = FakePacketQueue()
    status_store = FakeStableUserStatusStore({20: Ruleset.MANIA.value})
    handler = _handler(stats_query, packet_queue, stable_user_status_store=status_store)

    await handler.handle_stats_request(stats_request_payload([20]), user_id=3)

    assert stats_query.inputs == [
        CurrentUserStatsQueryInput(
            user_ids=(20,),
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
        )
    ]
    assert packet_queue.enqueued == [
        (
            3,
            (
                user_stats(
                    user_id=20,
                    status=0,
                    status_text="",
                    beatmap_md5="",
                    mods=0,
                    play_mode=3,
                    beatmap_id=0,
                    ranked_score=900_000,
                    accuracy=0.99,
                    play_count=5,
                    total_score=900_000,
                    rank=1,
                    pp=250,
                ),
            ),
        )
    ]


async def test_stats_request_preserves_target_user_current_status_fields() -> None:
    """Target userのcurrent status fieldをstats packetへ保持することを検証する.

    Returns:
        None: status text, beatmap, mods, play modeを含むpacketを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(
        stats_by_ruleset={
            Ruleset.MANIA: (
                UserCurrentStats(
                    user_id=20,
                    pp=Decimal("250"),
                    accuracy=0.99,
                    global_rank=1,
                    play_count=5,
                    ranked_score=900_000,
                    total_score=900_000,
                ),
            ),
        }
    )
    packet_queue = FakePacketQueue()
    status = StableUserStatus(
        status=2,
        status_text="playing",
        beatmap_md5="a" * 32,
        mods=64,
        play_mode=Ruleset.MANIA.value,
        beatmap_id=1234,
    )
    status_store = FakeStableUserStatusStore(statuses={20: status})
    handler = _handler(stats_query, packet_queue, stable_user_status_store=status_store)

    await handler.handle_stats_request(stats_request_payload([20]), user_id=3)

    assert packet_queue.enqueued == [
        (
            3,
            (
                user_stats(
                    user_id=20,
                    status=2,
                    status_text="playing",
                    beatmap_md5="a" * 32,
                    mods=64,
                    play_mode=3,
                    beatmap_id=1234,
                    ranked_score=900_000,
                    accuracy=0.99,
                    play_count=5,
                    total_score=900_000,
                    rank=1,
                    pp=250,
                ),
            ),
        )
    ]


async def test_stats_request_filters_offline_and_hidden_users_before_stats_read() -> None:
    """Offlineまたはhidden userをstats検索前に除外することを検証する.

    Returns:
        None: visible online userだけがqueryとpacketへ現れることを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(
        stats=(
            UserCurrentStats(user_id=20, pp=Decimal("50"), global_rank=2),
            UserCurrentStats(user_id=30, pp=Decimal("25"), global_rank=3),
            UserCurrentStats(user_id=99, pp=Decimal("10"), global_rank=4),
        )
    )
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeActiveSessionsByUserIdsQuery(
        (
            _session(20, privileges=Privileges.NORMAL | Privileges.UNRESTRICTED),
            _session(30, privileges=Privileges.NORMAL),
        )
    )
    handler = _handler(
        stats_query,
        packet_queue,
        active_sessions_by_user_ids_query=active_sessions_query,
    )

    await handler.handle_stats_request(stats_request_payload([20, 30, 99]), user_id=3)

    assert active_sessions_query.inputs == [
        GetActiveSessionsByUserIdsQueryInput(user_ids=(20, 30, 99))
    ]
    assert stats_query.inputs == [CurrentUserStatsQueryInput(user_ids=(20,))]
    assert packet_queue.enqueued == [
        (
            3,
            (
                user_stats(
                    user_id=20,
                    status=0,
                    status_text="",
                    beatmap_md5="",
                    mods=0,
                    play_mode=0,
                    beatmap_id=0,
                    ranked_score=0,
                    accuracy=0.0,
                    play_count=0,
                    total_score=0,
                    rank=2,
                    pp=50,
                ),
            ),
        )
    ]


async def test_stats_request_does_not_return_requesting_users_own_stats() -> None:
    """Requesting user自身のstatsを返さないことを検証する.

    Returns:
        None: requesterを除くonline userだけが検索とpacket化の対象になることを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(
        stats=(
            UserCurrentStats(user_id=20, pp=Decimal("50"), global_rank=2),
            UserCurrentStats(user_id=30, pp=Decimal("25"), global_rank=3),
        )
    )
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeActiveSessionsByUserIdsQuery(
        (
            _session(20),
            _session(30),
        )
    )
    handler = _handler(
        stats_query,
        packet_queue,
        active_sessions_by_user_ids_query=active_sessions_query,
    )

    await handler.handle_stats_request(stats_request_payload([20, 30]), user_id=20)

    assert active_sessions_query.inputs == [GetActiveSessionsByUserIdsQueryInput(user_ids=(30,))]
    assert stats_query.inputs == [CurrentUserStatsQueryInput(user_ids=(30,))]
    assert packet_queue.enqueued == [
        (
            20,
            (
                user_stats(
                    user_id=30,
                    status=0,
                    status_text="",
                    beatmap_md5="",
                    mods=0,
                    play_mode=0,
                    beatmap_id=0,
                    ranked_score=0,
                    accuracy=0.0,
                    play_count=0,
                    total_score=0,
                    rank=3,
                    pp=25,
                ),
            ),
        )
    ]


async def test_stats_request_returns_bot_stats_without_reading_user_stats() -> None:
    """BanchoBot requestがuser statsを読まずbot packetを返すことを検証する.

    Returns:
        None: empty session queryとbot user stats packetを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery()
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeActiveSessionsByUserIdsQuery(())
    handler = _handler(
        stats_query,
        packet_queue,
        active_sessions_by_user_ids_query=active_sessions_query,
    )

    await handler.handle_stats_request(
        stats_request_payload([BANCHO_BOT_IDENTITY.user_id, 20]),
        user_id=20,
    )

    assert active_sessions_query.inputs == [GetActiveSessionsByUserIdsQueryInput(user_ids=())]
    assert stats_query.inputs == []
    assert packet_queue.enqueued == [
        (
            20,
            (bot_user_stats_packet(),),
        )
    ]


async def test_stats_request_returns_bot_stats_in_requester_current_mode() -> None:
    """BanchoBot stats packetがrequesterのcurrent play modeを使うことを検証する.

    Returns:
        None: requesterの保存済みplay modeを持つbot packetを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery()
    packet_queue = FakePacketQueue()
    active_sessions_query = FakeActiveSessionsByUserIdsQuery(())
    status_store = FakeStableUserStatusStore({20: Ruleset.MANIA.value})
    handler = _handler(
        stats_query,
        packet_queue,
        stable_user_status_store=status_store,
        active_sessions_by_user_ids_query=active_sessions_query,
    )

    await handler.handle_stats_request(
        stats_request_payload([BANCHO_BOT_IDENTITY.user_id, 20]),
        user_id=20,
    )

    assert active_sessions_query.inputs == [GetActiveSessionsByUserIdsQueryInput(user_ids=())]
    assert stats_query.inputs == []
    assert packet_queue.enqueued == [
        (
            20,
            (bot_user_stats_packet(play_mode=Ruleset.MANIA.value),),
        )
    ]


async def test_stats_request_read_failure_does_not_enqueue_partial_stats() -> None:
    """Stats query失敗時にpartial packetをenqueueしないことを検証する.

    Returns:
        None: query inputは記録されてもqueue記録が空であることを確認して完了する.
    """
    stats_query = FakeCurrentUserStatsQuery(error=RuntimeError("stats unavailable"))
    packet_queue = FakePacketQueue()
    handler = _handler(stats_query, packet_queue)

    await handler.handle_stats_request(stats_request_payload([20]), user_id=3)

    assert stats_query.inputs == [CurrentUserStatsQueryInput(user_ids=(20,))]
    assert packet_queue.enqueued == []


def test_stats_request_handler_registers_stats_request_packet() -> None:
    """Stats request handlerがClientPacketID.STATS_REQUESTを登録することを検証する.

    Returns:
        None: dispatcherがstats request packetのhandlerを持つことを確認して完了する.
    """
    dispatcher = PacketDispatcher()
    handler = _handler(FakeCurrentUserStatsQuery(), FakePacketQueue())

    handler.register_all(dispatcher)

    assert ClientPacketID.STATS_REQUEST in dispatcher.get_handlers()


def _handler(
    stats_query: FakeCurrentUserStatsQuery,
    packet_queue: FakePacketQueue,
    *,
    stable_user_status_store: FakeStableUserStatusStore | None = None,
    active_sessions_by_user_ids_query: FakeActiveSessionsByUserIdsQuery | None = None,
) -> StatsRequestHandler:
    """指定fakeを注入したStatsRequestHandlerを構築する.

    Args:
        stats_query (FakeCurrentUserStatsQuery): current statsを返すquery fake.
        packet_queue (FakePacketQueue): serialized packetを記録するqueue fake.
        stable_user_status_store (FakeStableUserStatusStore | None): statusとplay modeを返す
            store fake.
        active_sessions_by_user_ids_query (FakeActiveSessionsByUserIdsQuery | None):
            可視sessionを返すquery fake.

    Returns:
        StatsRequestHandler: stable protocol用dependencyを持つstats handler.
    """
    return StatsRequestHandler(
        current_user_stats_query=cast(
            "CurrentUserStatsQuery",
            cast("object", stats_query),
        ),
        packet_queue=cast("PacketQueue", packet_queue),
        stable_user_status_store=cast(
            "StableUserStatusStore | None",
            stable_user_status_store,
        ),
        active_sessions_by_user_ids_query=cast(
            "GetActiveSessionsByUserIdsQuery | None",
            active_sessions_by_user_ids_query,
        ),
    )


def _session(
    user_id: int,
    *,
    privileges: Privileges = Privileges.NORMAL | Privileges.UNRESTRICTED,
) -> OnlineSessionSnapshot:
    """Stats可視性判定用のonline session snapshotを構築する.

    Args:
        user_id (int): snapshotへ設定するstable user ID.
        privileges (Privileges): 可視性判定に使うprivilege集合.

    Returns:
        OnlineSessionSnapshot: 日本のUTC+9 sessionとして初期化したsnapshot.
    """
    return OnlineSessionSnapshot(
        user_id=user_id,
        username=f"user-{user_id}",
        privileges=int(privileges),
        country="JP",
        utc_offset=9,
    )

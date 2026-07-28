"""UserStatsListenersのUSER_STATS packet fan-out contractを検証する."""

from __future__ import annotations

import typing
from decimal import Decimal
from typing import TYPE_CHECKING, final

from osu_server.domain.compatibility.stable import StableStatus, StableUserStatus
from osu_server.domain.events.scores import CurrentUserStatsUpdated
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserCurrentStats
from osu_server.infrastructure.state.memory.stable_user_status_store import (
    InMemoryStableUserStatusStore,
)
from osu_server.services.queries.scores import (
    CurrentUserStatsQuery,
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
)
from osu_server.transports.stable.bancho.listeners.user_stats import UserStatsListeners
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue


@final
class FakePacketQueue:
    """enqueueされたUSER_STATS packetを記録するPacketQueue fakeを提供する.

    Attributes:
        enqueued (list[tuple[int, bytes]]): recipient user IDとpacketの記録順序.
    """

    def __init__(self) -> None:
        """空のenqueue記録を持つpacket queue fakeを初期化する."""
        self.enqueued: list[tuple[int, bytes]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """recipientごとにpacketを記録する.

        Args:
            user_id (int): packetを受け取るstable userのID.
            *data (bytes): queueへ渡されたS2C packet群.

        Returns:
            None: 全packetを記録して完了し, 呼び出し側へ値を返さない.
        """
        for packet in data:
            self.enqueued.append((user_id, packet))


@final
class FakeCurrentUserStatsQuery:
    """設定済みstatsを返しquery inputを記録するCurrentUserStatsQuery fakeを提供する.

    Attributes:
        inputs (list[CurrentUserStatsQueryInput]): executeへ渡されたquery inputの順序.
    """

    def __init__(self, stats: tuple[UserCurrentStats, ...] = ()) -> None:
        """返却するcurrent stats snapshotを設定する.

        Args:
            stats (tuple[UserCurrentStats, ...]): executeが返すcurrent stats一覧.
        """
        self._stats = stats
        self.inputs: list[CurrentUserStatsQueryInput] = []

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """inputを記録して設定済みcurrent stats resultを返す.

        Args:
            input_data (CurrentUserStatsQueryInput): user, ruleset, playstyleを指定するquery input.

        Returns:
            CurrentUserStatsQueryResult: 設定済みstatsを含むquery result.
        """
        self.inputs.append(input_data)
        return CurrentUserStatsQueryResult(stats=self._stats)


@final
class FailingCurrentUserStatsQuery:
    """inputを記録して意図的に失敗するCurrentUserStatsQuery fakeを提供する.

    Attributes:
        inputs (list[CurrentUserStatsQueryInput]): 失敗前に記録するquery inputの順序.
    """

    def __init__(self) -> None:
        """空のquery input記録を持つ失敗fakeを初期化する."""
        self.inputs: list[CurrentUserStatsQueryInput] = []

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """inputを記録してfallback query failureを送出する.

        Args:
            input_data (CurrentUserStatsQueryInput): listenerが補完用に渡すquery input.

        Raises:
            RuntimeError: fallback stats query failureを再現する場合.
        """
        self.inputs.append(input_data)
        raise RuntimeError("stats query failed")


async def test_current_stats_event_enqueues_user_stats_packet_with_current_status() -> None:
    """Event snapshotと保存済みstatusからUSER_STATS packetをenqueueする契約を検証する.

    Returns:
        None: query未使用とcurrent statusを含むexact packetを確認して完了する.
    """
    packet_queue = FakePacketQueue()
    stats_query = FakeCurrentUserStatsQuery()
    status_store = InMemoryStableUserStatusStore()
    await status_store.set_status(
        20,
        StableUserStatus(
            status=StableStatus.Playing.value,
            status_text="Artist - Title [Hard]",
            beatmap_md5="a" * 32,
            mods=64,
            play_mode=0,
            beatmap_id=1234,
        ),
    )
    listeners = _listeners(
        packet_queue=packet_queue,
        stats_query=stats_query,
        status_store=status_store,
    )
    current_stats = UserCurrentStats(
        user_id=20,
        pp=Decimal("248.5"),
        accuracy=0.9876,
        global_rank=1,
        play_count=8,
        ranked_score=500_000,
        total_score=1_400_000,
    )

    await listeners.on_current_user_stats_updated(
        CurrentUserStatsUpdated(
            user_id=20,
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
            current_stats=current_stats,
        )
    )

    assert stats_query.inputs == []
    assert packet_queue.enqueued == [
        (
            20,
            user_stats(
                user_id=20,
                status=StableStatus.Playing.value,
                status_text="Artist - Title [Hard]",
                beatmap_md5="a" * 32,
                mods=64,
                play_mode=Ruleset.MANIA.value,
                beatmap_id=1234,
                ranked_score=500_000,
                accuracy=0.9876,
                play_count=8,
                total_score=1_400_000,
                rank=1,
                pp=249,
            ),
        )
    ]


async def test_current_stats_event_queries_stats_when_payload_has_no_snapshot() -> None:
    """Event snapshotがない場合にlistenerがqueryでstatsを補完する契約を検証する.

    Returns:
        None: query inputとdefault statusを使うpacketを検証して完了し, 呼び出し側へ値を返さない.
    """
    packet_queue = FakePacketQueue()
    current_stats = UserCurrentStats(user_id=20, pp=Decimal("100"), global_rank=3)
    stats_query = FakeCurrentUserStatsQuery((current_stats,))
    listeners = _listeners(packet_queue=packet_queue, stats_query=stats_query)

    await listeners.on_current_user_stats_updated(
        CurrentUserStatsUpdated(
            user_id=20,
            ruleset=Ruleset.TAIKO,
            playstyle=Playstyle.VANILLA,
        )
    )

    assert stats_query.inputs == [
        CurrentUserStatsQueryInput(
            user_ids=(20,),
            ruleset=Ruleset.TAIKO,
            playstyle=Playstyle.VANILLA,
        )
    ]
    assert packet_queue.enqueued == [
        (
            20,
            user_stats(
                user_id=20,
                status=StableStatus.Idle.value,
                status_text="",
                beatmap_md5="",
                mods=0,
                play_mode=Ruleset.TAIKO.value,
                beatmap_id=0,
                ranked_score=0,
                accuracy=0.0,
                play_count=0,
                total_score=0,
                rank=3,
                pp=100,
            ),
        )
    ]


async def test_current_stats_event_skips_packet_when_fallback_query_fails() -> None:
    """Fallback queryが失敗した場合にzero stats packetをenqueueしない契約を検証する.

    Returns:
        None: query inputと空queueを検証して完了し, 呼び出し側へ値を返さない.
    """
    packet_queue = FakePacketQueue()
    stats_query = FailingCurrentUserStatsQuery()
    listeners = _listeners(packet_queue=packet_queue, stats_query=stats_query)

    await listeners.on_current_user_stats_updated(
        CurrentUserStatsUpdated(
            user_id=20,
            ruleset=Ruleset.TAIKO,
            playstyle=Playstyle.VANILLA,
        )
    )

    assert stats_query.inputs == [
        CurrentUserStatsQueryInput(
            user_ids=(20,),
            ruleset=Ruleset.TAIKO,
            playstyle=Playstyle.VANILLA,
        )
    ]
    assert packet_queue.enqueued == []


def _listeners(
    *,
    packet_queue: FakePacketQueue,
    stats_query: FakeCurrentUserStatsQuery | FailingCurrentUserStatsQuery,
    status_store: InMemoryStableUserStatusStore | None = None,
) -> UserStatsListeners:
    """Typed fakeを注入したUserStatsListenersを構築する.

    Args:
        packet_queue (FakePacketQueue): enqueue結果を記録するqueue fake.
        stats_query (FakeCurrentUserStatsQuery | FailingCurrentUserStatsQuery): current stats
            query fake.
        status_store (InMemoryStableUserStatusStore | None): optional stable status fixture.

    Returns:
        UserStatsListeners: eventをUSER_STATS packetへ適応するlistener.
    """
    return UserStatsListeners(
        packet_queue=typing.cast("PacketQueue", typing.cast("object", packet_queue)),
        current_user_stats_query=typing.cast(
            "CurrentUserStatsQuery",
            typing.cast("object", stats_query),
        ),
        stable_user_status_store=status_store,
    )

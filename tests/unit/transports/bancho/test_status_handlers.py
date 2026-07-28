"""Bancho STATUS_CHANGE handlerのbeatmap warmupとstatus packet配送を検証する."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, final

import structlog.testing

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.domain.compatibility.stable import StableUserStatus
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserPerformanceBest
from osu_server.repositories.interfaces.queries.user_stats import (
    UserStatsRankInput,
    UserStatsSourceRead,
    UserStatsSourceRow,
)
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
    RequestBeatmapFileWarmupUseCase,
)
from osu_server.services.queries.identity import (
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.services.queries.scores import (
    CurrentUserStatsQuery,
    CurrentUserStatsQueryInput,
)
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.handlers.status import StatusChangeHandlers
from osu_server.transports.stable.bancho.protocol.c2s import status_change_payload
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import user_stats
from osu_server.transports.stable.bancho.protocol.types import StatusUpdate

if TYPE_CHECKING:
    from structlog.typing import EventDict

_USER_ID = 42
_CHECKSUM = "3b0aecd99eba50ffc7bff8da117d0e06"


@final
class RecordingWarmupUseCase:
    """Beatmap file warmup requestを記録するuse-case fake.

    Attributes:
        requests (list[BeatmapFileWarmupRequest]): executeへ渡されたwarmup requestの呼出順list.
        raise_on_execute (Exception | None): execute時に送出するsynthetic failure.
    """

    def __init__(self) -> None:
        """空のrequest記録とfailure未設定状態でfakeを初期化する."""
        self.requests: list[BeatmapFileWarmupRequest] = []
        self.raise_on_execute: Exception | None = None

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
        """Warmup requestを記録してrequested resultを返す.

        Args:
            request (BeatmapFileWarmupRequest): handlerが構築したbeatmap file warmup request.

        Returns:
            BeatmapFileWarmupResult: REQUESTED outcomeを持つ記録済みrequestのresult.

        Raises:
            Exception: raise_on_executeに設定されたfailureが存在する場合.
        """
        self.requests.append(request)
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        return BeatmapFileWarmupResult(
            outcome=BeatmapFileWarmupOutcome.REQUESTED,
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=request.beatmap_id,
            checksum_md5=request.checksum_md5,
            reason="recorded",
        )


@final
class RecordingStableUserStatusStore:
    """Status handlerが保存するstable statusとplay modeを記録するstore fake.

    Attributes:
        statuses (list[tuple[int, StableUserStatus]]): set_statusのuser IDとstatusの呼出順list.
        play_modes (list[tuple[int, int]]): 保存されたuser IDとplay modeの呼出順list.
    """

    def __init__(self) -> None:
        """空のstatusおよびplay mode記録を持つfakeを初期化する."""
        self.statuses: list[tuple[int, StableUserStatus]] = []
        self.play_modes: list[tuple[int, int]] = []

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """Userのstable statusとplay modeを記録する.

        Args:
            user_id (int): 更新対象のstable user ID.
            status (StableUserStatus): handlerが保存するcurrent stable status.

        Returns:
            None: statusと含まれるplay modeを記録して完了する.
        """
        self.statuses.append((user_id, status))
        self.play_modes.append((user_id, status.play_mode))

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """要求IDに記録済みのstatusだけを返す.

        Args:
            user_ids (tuple[int, ...]): statusを取得するstable user ID群.

        Returns:
            dict[int, StableUserStatus]: 最後まで記録された一致statusを含むmapping.
        """
        return {
            user_id: status
            for stored_user_id, status in self.statuses
            if stored_user_id in user_ids
            for user_id in (stored_user_id,)
        }

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        """Userのplay mode更新を記録する.

        Args:
            user_id (int): 更新対象のstable user ID.
            play_mode (int): handlerが保存するstable play mode値.

        Returns:
            None: user IDとplay modeの組を記録して完了する.
        """
        self.play_modes.append((user_id, play_mode))

    async def get_play_mode(self, user_id: int) -> int | None:
        """Protocol互換の未設定play modeを返す.

        Args:
            user_id (int): play modeを取得するstable user ID. fakeでは使用しない.

        Returns:
            int | None: 常にNone. 複数mode読出しはこのfakeで扱わない.
        """
        _ = user_id
        return None

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """Protocol互換の空play mode mappingを返す.

        Args:
            user_ids (tuple[int, ...]): play modeを取得するstable user ID群. fakeでは使用しない.

        Returns:
            dict[int, int]: 常に空mapping. 複数mode読出しはこのfakeで扱わない.
        """
        _ = user_ids
        return {}

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
class RecordingUserStatsQueryRepository:
    """Current user stats repository inputを記録して固定sourceを返すfake.

    Attributes:
        inputs (list[CurrentUserStatsQueryInput]): stats source読出しへ渡されたinputの呼出順list.
    """

    def __init__(self) -> None:
        """空のstats source読出し記録を持つfakeを初期化する."""
        self.inputs: list[CurrentUserStatsQueryInput] = []

    async def read_current_stats_sources(
        self,
        user_ids: tuple[int, ...],
        *,
        ruleset: Ruleset = Ruleset.OSU,
        playstyle: Playstyle = Playstyle.VANILLA,
    ) -> UserStatsSourceRead:
        """Stats source読出しinputを記録して固定performance sourceを返す.

        Args:
            user_ids (tuple[int, ...]): statsを読むstable user ID群.
            ruleset (Ruleset): performance集計に使うruleset.
            playstyle (Playstyle): performance集計に使うplaystyle.

        Returns:
            UserStatsSourceRead: _USER_IDのperformanceとrank inputを持つ固定source read.
        """
        self.inputs.append(
            CurrentUserStatsQueryInput(
                user_ids=user_ids,
                ruleset=ruleset,
                playstyle=playstyle,
            )
        )
        return UserStatsSourceRead(
            users=(
                UserStatsSourceRow(
                    user_id=_USER_ID,
                    play_count=5,
                    ranked_score=900_000,
                    total_score=900_000,
                    play_time_seconds=None,
                    best_performances=(UserPerformanceBest(pp=Decimal("250"), accuracy=0.99),),
                    accuracy=0.99,
                ),
            ),
            rank_inputs=(
                UserStatsRankInput(
                    user_id=_USER_ID,
                    best_performances=(UserPerformanceBest(pp=Decimal("250"), accuracy=0.99),),
                ),
            ),
        )


@final
class RecordingPacketQueue:
    """Status handlerがenqueueするstable packetを記録するqueue fake.

    Attributes:
        enqueued (list[tuple[int, tuple[bytes, ...]]]): 宛先user IDとpacket群の呼出順list.
    """

    def __init__(self) -> None:
        """空のenqueue記録を持つfakeを初期化する."""
        self.enqueued: list[tuple[int, tuple[bytes, ...]]] = []

    async def enqueue(self, user_id: int, *data: bytes) -> None:
        """宛先とserialized packet群を記録する.

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
class RecordingActiveSessionsQuery:
    """固定のonline session一覧を返すquery fake.

    Attributes:
        inputs (list[ListActiveSessionsQueryInput]): executeへ渡された検索inputの呼出順list.
    """

    def __init__(self, sessions: tuple[OnlineSessionSnapshot, ...]) -> None:
        """全session検索で返すonline snapshotを固定する.

        Args:
            sessions (tuple[OnlineSessionSnapshot, ...]): status fan-out先にするonline session群.
        """
        self.sessions = sessions
        self.inputs: list[ListActiveSessionsQueryInput] = []

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        """検索inputを記録して固定session一覧を返す.

        Args:
            input_data (ListActiveSessionsQueryInput): handlerが構築した全session検索input.

        Returns:
            ListActiveSessionsQueryResult: 初期化時のsessionを含むquery result.
        """
        self.inputs.append(input_data)
        return ListActiveSessionsQueryResult(sessions=self.sessions)


@final
class RecordingWarmupResolver:
    """Beatmap warmupが参照するidentityとoptionを記録するresolver fake.

    Attributes:
        calls (list[tuple[str, int | str, BeatmapResolveOptions | None]]): resolve種別と入力の
            呼出順list.
    """

    def __init__(self) -> None:
        """空のresolve呼出し記録を持つfakeを初期化する."""
        self.calls: list[tuple[str, int | str, BeatmapResolveOptions | None]] = []

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap IDによるresolve呼出しを記録してpending resultを返す.

        Args:
            beatmap_id (int): 解決対象のpositive beatmap ID.
            options (BeatmapResolveOptions | None): resolve時の追加option. 未指定時はNone.

        Returns:
            BeatmapResolveResult: metadata pendingとfile missingを表す固定result.
        """
        self.calls.append(("beatmap_id", beatmap_id, options))
        return _pending_result()

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Checksumによるresolve呼出しを記録してpending resultを返す.

        Args:
            checksum_md5 (str): 解決対象の32桁MD5 checksum.
            options (BeatmapResolveOptions | None): resolve時の追加option. 未指定時はNone.

        Returns:
            BeatmapResolveResult: metadata pendingとfile missingを表す固定result.
        """
        self.calls.append(("checksum", checksum_md5, options))
        return _pending_result()


def _status_payload(
    *,
    beatmap_id: int,
    beatmap_md5: str = _CHECKSUM,
    status_text: str = "playing",
    play_mode: int = 0,
) -> bytes:
    """Status change handlerへ渡すserialized payloadを構築する.

    Args:
        beatmap_id (int): status updateへ設定するbeatmap ID.
        beatmap_md5 (str): status updateへ設定するbeatmap MD5 checksum.
        status_text (str): stable clientへ表示するstatus text.
        play_mode (int): status updateへ設定するstable play mode値.

    Returns:
        bytes: STATUS_CHANGE protocol definitionでserializeしたpayload.
    """
    return status_change_payload(
        StatusUpdate(
            status=2,
            status_text=status_text,
            beatmap_md5=beatmap_md5,
            mods=0,
            play_mode=play_mode,
            beatmap_id=beatmap_id,
        )
    )


def _pending_result() -> BeatmapResolveResult:
    """Metadata pendingとfile missingを表すwarmup resolve resultを構築する.

    Returns:
        BeatmapResolveResult: beatmap identityを解決できないpending fetch result.
    """
    return BeatmapResolveResult(
        beatmap=None,
        beatmapset=None,
        eligibility=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        file_status=BeatmapFileState.MISSING,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="pending",
    )


def _warmup_logs(logs: list[EventDict]) -> list[EventDict]:
    """Captured structlog entryからbeatmap file warmup eventだけを抽出する.

    Args:
        logs (list[EventDict]): status handler実行中にcaptureしたstructlog entry.

    Returns:
        list[EventDict]: event fieldがbeatmap_file_warmupのentryを保つ出現順list.
    """
    return [entry for entry in logs if entry.get("event") == "beatmap_file_warmup"]


async def test_status_change_positive_beatmap_id_takes_priority_over_checksum() -> None:
    """Positive beatmap IDがchecksumより優先してwarmup identityになることを検証する.

    Returns:
        None: beatmap IDだけを持つstable status change warmup requestを確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)

    await handlers.handle_status_change(
        _status_payload(beatmap_id=1234, beatmap_md5=_CHECKSUM),
        user_id=_USER_ID,
    )

    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=_USER_ID,
            beatmap_id=1234,
            checksum_md5=None,
        )
    ]


async def test_status_change_stores_current_play_mode() -> None:
    """Status changeがcurrent play modeをstable status storeへ保存することを検証する.

    Returns:
        None: user IDとpayloadのplay modeが記録されることを確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    status_store = RecordingStableUserStatusStore()
    handlers = StatusChangeHandlers(
        beatmap_file_warmup=warmup,
        stable_user_status_store=status_store,
    )

    await handlers.handle_status_change(
        _status_payload(beatmap_id=1234, beatmap_md5=_CHECKSUM, play_mode=3),
        user_id=_USER_ID,
    )

    assert status_store.play_modes == [(_USER_ID, 3)]


async def test_status_change_returns_own_user_stats_for_current_play_mode() -> None:
    """Status changeが自身のcurrent play modeでstats packetを返すことを検証する.

    Returns:
        None: MANIA ruleset検索と自身宛てuser stats packetを確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    status_store = RecordingStableUserStatusStore()
    stats_repository = RecordingUserStatsQueryRepository()
    stats_query = CurrentUserStatsQuery(repository=stats_repository)
    packet_queue = RecordingPacketQueue()
    handlers = StatusChangeHandlers(
        beatmap_file_warmup=warmup,
        stable_user_status_store=status_store,
        current_user_stats_query=stats_query,
        packet_queue=packet_queue,
    )

    await handlers.handle_status_change(
        _status_payload(beatmap_id=1234, beatmap_md5=_CHECKSUM, play_mode=3),
        user_id=_USER_ID,
    )

    assert status_store.play_modes == [(_USER_ID, 3)]
    assert stats_repository.inputs == [
        CurrentUserStatsQueryInput(
            user_ids=(_USER_ID,),
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
        )
    ]
    expected_packet = user_stats(
        user_id=_USER_ID,
        status=2,
        status_text="playing",
        beatmap_md5=_CHECKSUM,
        mods=0,
        play_mode=3,
        beatmap_id=1234,
        ranked_score=900_000,
        accuracy=0.99,
        play_count=5,
        total_score=900_000,
        rank=1,
        pp=250,
    )
    assert packet_queue.enqueued == [
        (
            _USER_ID,
            (expected_packet,),
        ),
    ]


async def test_status_change_fans_out_user_stats_to_online_sessions() -> None:
    """Status changeのuser stats packetを自身とonline sessionへfan-outすることを検証する.

    Returns:
        None: active session queryと同一packetの宛先群を確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    status_store = RecordingStableUserStatusStore()
    stats_repository = RecordingUserStatsQueryRepository()
    stats_query = CurrentUserStatsQuery(repository=stats_repository)
    packet_queue = RecordingPacketQueue()
    active_sessions_query = RecordingActiveSessionsQuery(
        (
            OnlineSessionSnapshot(
                user_id=100,
                username="Other",
                privileges=0,
                country="JP",
                utc_offset=9,
            ),
            OnlineSessionSnapshot(
                user_id=_USER_ID,
                username="Self",
                privileges=0,
                country="JP",
                utc_offset=9,
            ),
        )
    )
    handlers = StatusChangeHandlers(
        beatmap_file_warmup=warmup,
        stable_user_status_store=status_store,
        current_user_stats_query=stats_query,
        packet_queue=packet_queue,
        active_sessions_query=active_sessions_query,
    )

    await handlers.handle_status_change(
        _status_payload(beatmap_id=1234, beatmap_md5=_CHECKSUM, play_mode=3),
        user_id=_USER_ID,
    )

    assert active_sessions_query.inputs == [ListActiveSessionsQueryInput()]
    assert [recipient_id for recipient_id, _ in packet_queue.enqueued] == [_USER_ID, 100]
    assert packet_queue.enqueued[0][1] == packet_queue.enqueued[1][1]


async def test_request_status_returns_own_user_stats_for_stored_play_mode() -> None:
    """Request statusが保存済みplay modeで自身のstats packetを返すことを検証する.

    Returns:
        None: MANIA ruleset検索とwarmupなしの自身宛てpacketを確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    status_store = RecordingStableUserStatusStore()
    await status_store.set_status(
        _USER_ID,
        StableUserStatus(
            status=2,
            status_text="playing",
            beatmap_md5=_CHECKSUM,
            mods=0,
            play_mode=Ruleset.MANIA.value,
            beatmap_id=1234,
        ),
    )
    stats_repository = RecordingUserStatsQueryRepository()
    stats_query = CurrentUserStatsQuery(repository=stats_repository)
    packet_queue = RecordingPacketQueue()
    handlers = StatusChangeHandlers(
        beatmap_file_warmup=warmup,
        stable_user_status_store=status_store,
        current_user_stats_query=stats_query,
        packet_queue=packet_queue,
    )

    await handlers.handle_request_status(b"", user_id=_USER_ID)

    assert stats_repository.inputs == [
        CurrentUserStatsQueryInput(
            user_ids=(_USER_ID,),
            ruleset=Ruleset.MANIA,
            playstyle=Playstyle.VANILLA,
        )
    ]
    assert warmup.requests == []
    assert packet_queue.enqueued == [
        (
            _USER_ID,
            (
                user_stats(
                    user_id=_USER_ID,
                    status=2,
                    status_text="playing",
                    beatmap_md5=_CHECKSUM,
                    mods=0,
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


async def test_status_change_checksum_fallback_uses_32_hex_when_id_is_not_positive() -> None:
    """Non-positive beatmap ID時に32桁checksumをwarmup identityとして使うことを検証する.

    Returns:
        None: beatmap IDなしでpayloadのchecksumを持つwarmup requestを確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)

    await handlers.handle_status_change(
        _status_payload(beatmap_id=0, beatmap_md5=_CHECKSUM.upper()),
        user_id=_USER_ID,
    )

    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=_USER_ID,
            beatmap_id=None,
            checksum_md5=_CHECKSUM.upper(),
        )
    ]


async def test_status_change_without_beatmap_identity_logs_skip_without_fetch() -> None:
    """Beatmap identityなしのstatus changeがfetchせずskip eventを記録することを検証する.

    Returns:
        None: resolver未呼出しとskipped_no_identity eventのfieldを確認して完了する.
    """
    resolver = RecordingWarmupResolver()
    handlers = StatusChangeHandlers(beatmap_file_warmup=RequestBeatmapFileWarmupUseCase(resolver))

    with structlog.testing.capture_logs() as logs:
        await handlers.handle_status_change(
            _status_payload(beatmap_id=0, beatmap_md5="not-a-32-hex-checksum"),
            user_id=_USER_ID,
        )

    assert resolver.calls == []
    events = _warmup_logs(logs)
    assert len(events) == 1
    assert events[0]["entrance"] == "stable_status_change"
    assert events[0]["outcome"] == "skipped_no_identity"
    assert events[0]["reason"] == "no_beatmap_identity"


async def test_status_change_decode_failure_is_logged_without_warmup_call() -> None:
    """Malformed status payloadがwarmupせずdecode failure eventを記録することを検証する.

    Returns:
        None: warmup未呼出しとraw payloadを含まないdiagnostic eventを確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)

    with structlog.testing.capture_logs() as logs:
        await handlers.handle_status_change(b"\x02\x0b", user_id=_USER_ID)

    assert warmup.requests == []
    events = [
        entry for entry in logs if entry.get("event") == "status_change_warmup_decode_failed"
    ]
    assert len(events) == 1
    assert events[0]["user_id"] == _USER_ID
    assert events[0]["payload_size"] == 2
    assert "payload" not in events[0]
    assert "raw_payload" not in events[0]


async def test_status_change_warmup_failure_is_logged_without_raising() -> None:
    """Warmup failureが呼出し元へ送出されずredacted eventになることを検証する.

    Returns:
        None: request記録とexception typeだけを含むfailure eventを確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    warmup.raise_on_execute = RuntimeError("downstream failure with token=secret")
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)

    with structlog.testing.capture_logs() as logs:
        await handlers.handle_status_change(_status_payload(beatmap_id=987), user_id=_USER_ID)

    assert len(warmup.requests) == 1
    events = [entry for entry in logs if entry.get("event") == "status_change_warmup_failed"]
    assert len(events) == 1
    assert events[0]["user_id"] == _USER_ID
    assert events[0]["exception_type"] == "RuntimeError"
    assert "token" not in events[0]
    assert "payload" not in events[0]
    assert "raw_payload" not in events[0]


async def test_status_change_repeated_reference_uses_consistent_warmup_identity() -> None:
    """同一status payloadの反復が同一warmup identityを使うことを検証する.

    Returns:
        None: 2回のrequestが同じbeatmap IDとchecksumなしを持つことを確認して完了する.
    """
    warmup = RecordingWarmupUseCase()
    handlers = StatusChangeHandlers(beatmap_file_warmup=warmup)
    payload = _status_payload(beatmap_id=555, beatmap_md5=_CHECKSUM)

    await handlers.handle_status_change(payload, user_id=_USER_ID)
    await handlers.handle_status_change(payload, user_id=_USER_ID)

    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=_USER_ID,
            beatmap_id=555,
            checksum_md5=None,
        ),
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=_USER_ID,
            beatmap_id=555,
            checksum_md5=None,
        ),
    ]


def test_status_change_handler_registers_status_change_packet() -> None:
    """StatusChangeHandlersがSTATUS_CHANGEとREQUEST_STATUS packetを登録することを検証する.

    Returns:
        None: dispatcherが2つのclient packet IDのhandlerを持つことを確認して完了する.
    """
    dispatcher = PacketDispatcher()
    handlers = StatusChangeHandlers(beatmap_file_warmup=RecordingWarmupUseCase())

    handlers.register_all(dispatcher)

    assert ClientPacketID.STATUS_CHANGE in dispatcher.get_handlers()
    assert ClientPacketID.REQUEST_STATUS in dispatcher.get_handlers()

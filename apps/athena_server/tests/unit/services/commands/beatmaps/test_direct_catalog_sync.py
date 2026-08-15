"""osu!direct catalog schedulerの共有budgetと優先度契約を検証するmodule."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from structlog.testing import capture_logs

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    DirectCoverageKind,
    DirectCoverageRecord,
    DirectCoverageStatusScope,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.beatmaps.direct_catalog_sync import (
    DirectCatalogScheduleOutcome,
    DirectCatalogScheduler,
    DirectCatalogWorkKind,
    DirectFeedSync,
    DirectFeedWindow,
    DirectFeedWindowFetchResult,
    DirectRangeCrawl,
    DirectRangeCrawlChunk,
    DirectRangeCrawlFetchResult,
    RecordDirectSearchCoverageUseCase,
)

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)


@dataclass(slots=True)
class RecordingCatalogWork:
    """Scheduler testで実行済みworkの順序を記録するcallableを提供する.

    Attributes:
        label (str): workが実行されたときに記録する識別子.
        calls (list[str]): 実行順を保存する共有list.
    """

    label: str
    calls: list[str]

    async def __call__(self) -> None:
        """Work実行を共有listへ記録する.

        Returns:
            None: labelを追加して完了し, 呼び出し側へ値を返さない.
        """
        self.calls.append(self.label)


@dataclass(slots=True)
class FailingCatalogWork:
    """Scheduler testでsanitize対象の例外を送出するcallableを提供する.

    Attributes:
        secret_value (str): exception messageへ混ぜる機密値のsentinel.
    """

    secret_value: str = "secret-token full upstream body"

    async def __call__(self) -> None:
        """Catalog work失敗を再現する.

        Returns:
            None: 正常終了せず例外を送出する.

        Raises:
            RuntimeError: schedulerのfailure diagnosticsを検証するため常に発生する.
        """
        raise RuntimeError(self.secret_value)


@dataclass(slots=True)
class RecordingFeedWindowFetcher:
    """Feed window fetchの結果と呼出対象を記録するtest double.

    Attributes:
        result (DirectFeedWindowFetchResult): feed windowから返すbeatmapset snapshots.
        calls (list[DirectFeedWindow]): fetch対象として受け取ったwindow列.
    """

    result: DirectFeedWindowFetchResult
    calls: list[DirectFeedWindow]

    async def fetch_feed_window(
        self,
        window: DirectFeedWindow,
    ) -> DirectFeedWindowFetchResult:
        """Feed window取得要求を記録し固定結果を返す.

        Args:
            window (DirectFeedWindow): sync対象のfeed window.

        Returns:
            DirectFeedWindowFetchResult: testで設定したfeed window結果.
        """
        self.calls.append(window)
        return self.result


@dataclass(slots=True)
class FailingFeedWindowFetcher:
    """Feed window取得の失敗を再現するtest double.

    Attributes:
        secret_value (str): raw upstream bodyを含むsentinel error message.
    """

    secret_value: str = "secret-token full upstream body"

    async def fetch_feed_window(
        self,
        window: DirectFeedWindow,
    ) -> DirectFeedWindowFetchResult:
        """Feed window取得で常に例外を送出する.

        Args:
            window (DirectFeedWindow): sync対象のfeed window.

        Returns:
            DirectFeedWindowFetchResult: 正常終了しないため返されない.

        Raises:
            RuntimeError: schedulerとfailure coverageのsanitize契約を検証するため発生する.
        """
        _ = window
        raise RuntimeError(self.secret_value)


@dataclass(slots=True)
class RecordingRangeCrawlFetcher:
    """ID range crawlの結果と呼出対象を記録するtest double.

    Attributes:
        result (DirectRangeCrawlFetchResult): id range crawlから返すbeatmapset snapshots.
        calls (list[DirectRangeCrawlChunk]): crawl対象として受け取ったchunk列.
        request_count_per_beatmapset (int): 1 IDあたりに予約するupstream request数.
    """

    result: DirectRangeCrawlFetchResult
    calls: list[DirectRangeCrawlChunk]
    request_count_per_beatmapset: int = 1

    def request_count_for_chunk(self, chunk: DirectRangeCrawlChunk) -> int:
        """ID range chunkで予約するrequest数を返す.

        Args:
            chunk (DirectRangeCrawlChunk): crawl対象のid range chunk.

        Returns:
            int: range sizeにrequest_count_per_beatmapsetを掛けた予約数.
        """
        return (
            chunk.to_beatmapset_id - chunk.from_beatmapset_id + 1
        ) * self.request_count_per_beatmapset

    async def fetch_id_range(
        self,
        chunk: DirectRangeCrawlChunk,
    ) -> DirectRangeCrawlFetchResult:
        """ID range crawl要求を記録し固定結果を返す.

        Args:
            chunk (DirectRangeCrawlChunk): crawl対象のid range chunk.

        Returns:
            DirectRangeCrawlFetchResult: testで設定したcrawl結果.
        """
        self.calls.append(chunk)
        return self.result


@dataclass(slots=True)
class FailingRangeCrawlFetcher:
    """ID range crawl取得の失敗を再現するtest double.

    Attributes:
        secret_value (str): raw upstream bodyを含むsentinel error message.
    """

    secret_value: str = "secret-token full upstream body"

    def request_count_for_chunk(self, chunk: DirectRangeCrawlChunk) -> int:
        """ID range chunkのID数をrequest予約数として返す.

        Args:
            chunk (DirectRangeCrawlChunk): crawl対象のid range chunk.

        Returns:
            int: chunkに含まれるBeatmapSet ID数.
        """
        return chunk.to_beatmapset_id - chunk.from_beatmapset_id + 1

    async def fetch_id_range(
        self,
        chunk: DirectRangeCrawlChunk,
    ) -> DirectRangeCrawlFetchResult:
        """ID range crawl取得で常に例外を送出する.

        Args:
            chunk (DirectRangeCrawlChunk): crawl対象のid range chunk.

        Returns:
            DirectRangeCrawlFetchResult: 正常終了しないため返されない.

        Raises:
            RuntimeError: schedulerとfailure coverageのsanitize契約を検証するため発生する.
        """
        _ = chunk
        raise RuntimeError(self.secret_value)


async def test_concurrent_point_lookup_consumes_budget_before_catalog_crawl() -> None:
    """同時に競合するpoint lookupがcatalog crawlより先に共有budgetを使う契約を検証する.

    Returns:
        None: point lookupのみが実行され,catalog crawlがretry可能なdelayになることを確認する.
    """
    calls: list[str] = []
    scheduler = DirectCatalogScheduler(request_budget_per_minute=1)

    crawl_task = asyncio.create_task(
        scheduler.run(
            DirectCatalogWorkKind.ID_RANGE_CRAWL,
            RecordingCatalogWork("crawl", calls),
        )
    )
    point_task = asyncio.create_task(
        scheduler.run(
            DirectCatalogWorkKind.POINT_LOOKUP,
            RecordingCatalogWork("point", calls),
        )
    )

    point_result, crawl_result = await asyncio.gather(point_task, crawl_task)

    assert point_result.outcome is DirectCatalogScheduleOutcome.COMPLETED
    assert crawl_result.outcome is DirectCatalogScheduleOutcome.DELAYED
    assert crawl_result.retry_eligible is True
    assert crawl_result.retry_after_seconds is not None
    assert crawl_result.retry_after_seconds > 0
    assert calls == ["point"]


async def test_shared_budget_delays_catalog_work_with_operator_retry_diagnostics() -> None:
    """Point lookupが消費した共有budgetによりcatalog workがdelay診断を返す契約を検証する.

    Returns:
        None: feed syncとrange crawlが同じbudget枯渇を観測し, retry stateをlogへ出すことを確認する.
    """
    calls: list[str] = []
    scheduler = DirectCatalogScheduler(request_budget_per_minute=1)

    point_result = await scheduler.run(
        DirectCatalogWorkKind.POINT_LOOKUP,
        RecordingCatalogWork("point", calls),
    )
    with capture_logs() as logs:
        feed_result = await scheduler.run(
            DirectCatalogWorkKind.FEED_SYNC,
            RecordingCatalogWork("feed", calls),
        )
        range_result = await scheduler.run(
            DirectCatalogWorkKind.ID_RANGE_CRAWL,
            RecordingCatalogWork("range", calls),
        )

    assert point_result.outcome is DirectCatalogScheduleOutcome.COMPLETED
    assert feed_result.outcome is DirectCatalogScheduleOutcome.DELAYED
    assert range_result.outcome is DirectCatalogScheduleOutcome.DELAYED
    assert calls == ["point"]

    events = [entry for entry in logs if entry["event"] == "osu_direct_catalog_sync_delayed"]
    assert {event["work_kind"] for event in events} == {"feed_sync", "id_range_crawl"}
    assert all(event["retry_eligible"] is True for event in events)
    assert all(event["retry_after_seconds"] > 0 for event in events)


async def test_shared_budget_allows_request_count_that_exactly_fills_remaining_budget() -> None:
    """request_countが残budgetを使い切る場合にworkを実行する契約を検証する.

    Returns:
        None: 予約数が残budgetと等しいcatalog workが完了することを確認する.
    """
    calls: list[str] = []
    scheduler = DirectCatalogScheduler(request_budget_per_minute=3)
    _ = await scheduler.run(
        DirectCatalogWorkKind.POINT_LOOKUP,
        RecordingCatalogWork("point", calls),
    )

    result = await scheduler.run(
        DirectCatalogWorkKind.ID_RANGE_CRAWL,
        RecordingCatalogWork("range", calls),
        request_count=2,
    )

    assert result.outcome is DirectCatalogScheduleOutcome.COMPLETED
    assert calls == ["point", "range"]


async def test_shared_budget_delays_when_request_count_exceeds_remaining_budget() -> None:
    """request_countが残budgetを超える場合にworkを実行しない契約を検証する.

    Returns:
        None: budget枯渇結果と未実行のwork記録を確認する.
    """
    calls: list[str] = []
    scheduler = DirectCatalogScheduler(request_budget_per_minute=3)
    _ = await scheduler.run(
        DirectCatalogWorkKind.POINT_LOOKUP,
        RecordingCatalogWork("point", calls),
    )

    result = await scheduler.run(
        DirectCatalogWorkKind.ID_RANGE_CRAWL,
        RecordingCatalogWork("range", calls),
        request_count=3,
    )

    assert result.outcome is DirectCatalogScheduleOutcome.DELAYED
    assert result.retry_eligible is True
    assert calls == ["point"]


async def test_shared_budget_rejects_non_positive_request_count() -> None:
    """request_countが正でない呼び出しを拒否する契約を検証する.

    Returns:
        None: ValueErrorが発生しworkが実行されないことを確認する.
    """
    calls: list[str] = []
    scheduler = DirectCatalogScheduler(request_budget_per_minute=3)

    with pytest.raises(ValueError, match="request_count must be positive"):
        _ = await scheduler.run(
            DirectCatalogWorkKind.ID_RANGE_CRAWL,
            RecordingCatalogWork("range", calls),
            request_count=0,
        )
    assert calls == []


async def test_shared_budget_rejects_range_larger_than_window_budget_without_retry() -> None:
    """Window上限より大きいrequest_countを非retry失敗として返す契約を検証する.

    Returns:
        None: oversized workがdelay retryにならずworkを実行しないことを確認する.
    """
    calls: list[str] = []
    scheduler = DirectCatalogScheduler(request_budget_per_minute=3)

    result = await scheduler.run(
        DirectCatalogWorkKind.ID_RANGE_CRAWL,
        RecordingCatalogWork("range", calls),
        request_count=4,
    )

    assert result.outcome is DirectCatalogScheduleOutcome.FAILED
    assert result.retry_eligible is False
    assert result.failure_reason == "request_count exceeds upstream budget"
    assert calls == []


async def test_catalog_failure_returns_sanitized_retry_diagnostics() -> None:
    """Catalog work失敗をsanitize済みのoperator向けretry診断へ変換する契約を検証する.

    Returns:
        None: raw upstream bodyを結果やlogへ含めず,失敗とretry可否を返すことを確認する.
    """
    scheduler = DirectCatalogScheduler(request_budget_per_minute=1)

    with capture_logs() as logs:
        result = await scheduler.run(
            DirectCatalogWorkKind.FEED_SYNC,
            FailingCatalogWork(),
        )

    assert result.outcome is DirectCatalogScheduleOutcome.FAILED
    assert result.retry_eligible is True
    assert result.failure_reason == "RuntimeError: catalog work failed"
    assert result.retry_after_seconds is None
    assert "secret-token" not in repr(result)
    assert "upstream body" not in repr(result)

    events = [entry for entry in logs if entry["event"] == "osu_direct_catalog_sync_failed"]
    assert len(events) == 1
    assert events[0]["work_kind"] == "feed_sync"
    assert events[0]["exception_type"] == "RuntimeError"
    assert events[0]["retry_eligible"] is True
    assert events[0]["failure_reason"] == "RuntimeError: catalog work failed"
    assert "secret-token" not in repr(logs)
    assert "upstream body" not in repr(logs)


async def test_feed_window_sync_saves_metadata_and_completed_coverage() -> None:
    """Feed window成功時にmetadata保存後のcoverage完了recordを保存する契約を検証する.

    2件のfeed-observed beatmapsetを同期し, metadata保存pathでsearch projectionが作られた後,
    source, status scope, sort/window, observed ID範囲, cursor, completion timeが記録されることを
    確認する.

    Returns:
        None: 保存済みmetadata, search projection, coverage recordを検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    window = _make_feed_window(window_key="page-1")
    fetcher = RecordingFeedWindowFetcher(
        result=DirectFeedWindowFetchResult(
            beatmapsets=(
                _make_feed_snapshot(beatmapset_id=1_000),
                _make_feed_snapshot(beatmapset_id=1_010),
            ),
            cursor="cursor:next",
        ),
        calls=[],
    )
    sync = DirectFeedSync(
        unit_of_work_factory=factory,
        scheduler=DirectCatalogScheduler(request_budget_per_minute=10),
        feed_window_fetcher=fetcher,
    )

    result = await sync.execute(window)

    snapshot = factory.snapshot()
    assert result.outcome is DirectCatalogScheduleOutcome.COMPLETED
    assert fetcher.calls == [window]
    assert snapshot.beatmapsets_by_id[1_000].title == "Feed Title 1000"
    assert snapshot.search_documents_by_beatmapset_id[1_000].is_active is True
    assert snapshot.search_documents_by_beatmapset_id[1_010].is_active is True

    coverage = snapshot.direct_coverage_records_by_scope[
        _coverage_key(window, from_beatmapset_id=1_000, to_beatmapset_id=1_010)
    ]
    assert coverage.coverage_kind is DirectCoverageKind.FEED_WINDOW
    assert coverage.source is BeatmapMetadataSource.MIRROR
    assert coverage.status_scope is DirectCoverageStatusScope.RANKED
    assert coverage.sort_key == "newest"
    assert coverage.window_key == "page-1"
    assert coverage.from_beatmapset_id == 1_000
    assert coverage.to_beatmapset_id == 1_010
    assert coverage.cursor == "cursor:next"
    assert coverage.completed_at is not None
    assert coverage.failed_at is None
    assert coverage.failure_reason is None


async def test_feed_window_failure_records_failed_coverage_without_metadata() -> None:
    """Feed window失敗時にcovered扱いせずretry可能な失敗recordだけを保存する契約を検証する.

    Raw upstream bodyを含む例外を送出し, metadata/search projectionを作らず,失敗時刻とsanitize済み
    reasonだけをcoverage stateへ残すことを確認する.

    Returns:
        None: failure result, coverage failure state, metadata未保存を検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    window = _make_feed_window(window_key="page-2")
    sync = DirectFeedSync(
        unit_of_work_factory=factory,
        scheduler=DirectCatalogScheduler(request_budget_per_minute=10),
        feed_window_fetcher=FailingFeedWindowFetcher(),
    )

    result = await sync.execute(window)

    snapshot = factory.snapshot()
    coverage = snapshot.direct_coverage_records_by_scope[
        _coverage_key(window, from_beatmapset_id=0, to_beatmapset_id=0)
    ]
    assert result.outcome is DirectCatalogScheduleOutcome.FAILED
    assert result.retry_eligible is True
    assert coverage.completed_at is None
    assert coverage.failed_at is not None
    assert coverage.failure_reason == result.failure_reason
    assert snapshot.beatmapsets_by_id == {}
    assert snapshot.search_documents_by_beatmapset_id == {}
    assert "secret-token" not in repr(result)
    assert "upstream body" not in repr(result)
    assert "secret-token" not in repr(coverage)
    assert "upstream body" not in repr(coverage)


async def test_range_crawl_saves_metadata_and_completed_id_range_coverage() -> None:
    """ID range crawl成功時にmetadata保存後の強いcoverage完了recordを保存する契約を検証する.

    Configured chunkのID範囲をcrawlし, metadata保存pathでsearch projectionが作られた後,
    source, status scope, from/to ID, completion timeがID_RANGEとして記録されることを確認する.

    Returns:
        None: 保存済みmetadata, search projection, id range coverage recordを検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    chunk = _make_range_chunk(from_beatmapset_id=2_000, to_beatmapset_id=2_010)
    fetcher = RecordingRangeCrawlFetcher(
        result=DirectRangeCrawlFetchResult(
            beatmapsets=(
                _make_feed_snapshot(beatmapset_id=2_000),
                _make_feed_snapshot(beatmapset_id=2_010),
            )
        ),
        calls=[],
    )
    crawl = DirectRangeCrawl(
        unit_of_work_factory=factory,
        scheduler=DirectCatalogScheduler(request_budget_per_minute=11),
        range_crawl_fetcher=fetcher,
    )

    result = await crawl.execute(chunk)

    snapshot = factory.snapshot()
    assert result.outcome is DirectCatalogScheduleOutcome.COMPLETED
    assert fetcher.calls == [chunk]
    assert snapshot.beatmapsets_by_id[2_000].title == "Feed Title 2000"
    assert snapshot.search_documents_by_beatmapset_id[2_000].is_active is True
    assert snapshot.search_documents_by_beatmapset_id[2_010].is_active is True

    coverage = snapshot.direct_coverage_records_by_scope[_range_coverage_key(chunk)]
    assert coverage.coverage_kind is DirectCoverageKind.ID_RANGE
    assert coverage.source is BeatmapMetadataSource.MIRROR
    assert coverage.status_scope is DirectCoverageStatusScope.RANKED
    assert coverage.sort_key == "id-range"
    assert coverage.window_key == "2000-2010"
    assert coverage.from_beatmapset_id == 2_000
    assert coverage.to_beatmapset_id == 2_010
    assert coverage.cursor is None
    assert coverage.completed_at is not None
    assert coverage.failed_at is None
    assert coverage.failure_reason is None


async def test_range_crawl_reserves_reported_upstream_request_count() -> None:
    """Range crawlがfetcher報告のrequest数でbudget予約する契約を検証する.

    Mirror fallbackのように1 IDあたり複数HTTP試行がありうる条件で、range sizeでは残budget内でも
    報告request数では枯渇するchunkがfetchされないことを確認する.

    Returns:
        None: request_count_for_chunkの値がscheduler予約に使われることを検証する.
    """
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    chunk = _make_range_chunk(from_beatmapset_id=2_000, to_beatmapset_id=2_004)
    scheduler = DirectCatalogScheduler(request_budget_per_minute=10)
    _ = await scheduler.run(
        DirectCatalogWorkKind.POINT_LOOKUP,
        RecordingCatalogWork("point", []),
    )
    fetcher = RecordingRangeCrawlFetcher(
        result=DirectRangeCrawlFetchResult(beatmapsets=()),
        calls=[],
        request_count_per_beatmapset=2,
    )
    crawl = DirectRangeCrawl(
        unit_of_work_factory=factory,
        scheduler=scheduler,
        range_crawl_fetcher=fetcher,
    )

    result = await crawl.execute(chunk)

    assert result.outcome is DirectCatalogScheduleOutcome.DELAYED
    assert result.retry_eligible is True
    assert fetcher.calls == []
    assert factory.snapshot().direct_coverage_records_by_scope == {}


async def test_range_crawl_failure_records_failed_chunk_without_metadata() -> None:
    """ID range crawl失敗時にcovered扱いせずretry可能な失敗recordだけを保存する契約を検証する.

    Raw upstream bodyを含む例外を送出し, metadata/search projectionを作らず,失敗時刻とsanitize済み
    reasonだけをID_RANGE coverage stateへ残すことを確認する.

    Returns:
        None: failure result, id range failure state, metadata未保存を検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    chunk = _make_range_chunk(from_beatmapset_id=2_020, to_beatmapset_id=2_030)
    crawl = DirectRangeCrawl(
        unit_of_work_factory=factory,
        scheduler=DirectCatalogScheduler(request_budget_per_minute=11),
        range_crawl_fetcher=FailingRangeCrawlFetcher(),
    )

    result = await crawl.execute(chunk)

    snapshot = factory.snapshot()
    coverage = snapshot.direct_coverage_records_by_scope[_range_coverage_key(chunk)]
    assert result.outcome is DirectCatalogScheduleOutcome.FAILED
    assert result.retry_eligible is True
    assert coverage.coverage_kind is DirectCoverageKind.ID_RANGE
    assert coverage.completed_at is None
    assert coverage.failed_at is not None
    assert coverage.failure_reason == result.failure_reason
    assert snapshot.beatmapsets_by_id == {}
    assert snapshot.search_documents_by_beatmapset_id == {}
    assert "secret-token" not in repr(result)
    assert "upstream body" not in repr(result)
    assert "secret-token" not in repr(coverage)
    assert "upstream body" not in repr(coverage)


async def test_record_direct_search_coverage_saves_record() -> None:
    """検索時に観測したcoverage recordをcommand境界で保存する契約を検証する.

    Returns:
        None: coverage recordがUnit of Workへcommitされることを確認して完了する.
    """
    factory = InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())
    record = DirectCoverageRecord(
        coverage_kind=DirectCoverageKind.FEED_WINDOW,
        source=BeatmapMetadataSource.MIRROR,
        status_scope=DirectCoverageStatusScope.ALL,
        sort_key="upstream-search",
        window_key="search:0123456789abcdef0123456789abcdef",
        from_beatmapset_id=1_000,
        to_beatmapset_id=1_010,
        cursor=None,
        completed_at=datetime.now(UTC),
        failed_at=None,
        failure_reason=None,
    )
    command = RecordDirectSearchCoverageUseCase(factory)

    await command.execute(record)

    snapshot = factory.snapshot()
    assert (
        snapshot.direct_coverage_records_by_scope[
            (
                DirectCoverageKind.FEED_WINDOW.value,
                BeatmapMetadataSource.MIRROR.value,
                DirectCoverageStatusScope.ALL.value,
                "upstream-search",
                "search:0123456789abcdef0123456789abcdef",
                1_000,
                1_010,
            )
        ]
        == record
    )


def _make_feed_window(*, window_key: str) -> DirectFeedWindow:
    """Feed sync test用のranked newest windowを作成する.

    Args:
        window_key (str): coverage scopeへ保存するwindow識別子.

    Returns:
        DirectFeedWindow: mirror ranked newest feed window.
    """
    return DirectFeedWindow(
        source=BeatmapMetadataSource.MIRROR,
        status_scope=DirectCoverageStatusScope.RANKED,
        sort_key="newest",
        window_key=window_key,
    )


def _make_range_chunk(*, from_beatmapset_id: int, to_beatmapset_id: int) -> DirectRangeCrawlChunk:
    """ID range crawl test用のranked chunkを作成する.

    Args:
        from_beatmapset_id (int): crawl chunk開始ID.
        to_beatmapset_id (int): crawl chunk終了ID.

    Returns:
        DirectRangeCrawlChunk: mirror ranked id range chunk.
    """
    return DirectRangeCrawlChunk(
        source=BeatmapMetadataSource.MIRROR,
        status_scope=DirectCoverageStatusScope.RANKED,
        from_beatmapset_id=from_beatmapset_id,
        to_beatmapset_id=to_beatmapset_id,
    )


def _make_feed_snapshot(*, beatmapset_id: int) -> BeatmapsetSnapshot:
    """Feed sync test用の1 child beatmapset snapshotを作成する.

    Args:
        beatmapset_id (int): 作成するbeatmapset ID.

    Returns:
        BeatmapsetSnapshot: ranked childを持つmirror由来snapshot.
    """
    beatmap_id = beatmapset_id + 100_000
    beatmap = BeatmapSnapshot(
        beatmap_id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=f"{beatmap_id:032x}",
        mode=BeatmapMode.OSU,
        version=f"Difficulty {beatmapset_id}",
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
        official_last_updated_at=_NOW,
    )
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=f"Feed Artist {beatmapset_id}",
        title=f"Feed Title {beatmapset_id}",
        creator="Direct Mapper",
        source=BeatmapMetadataSource.MIRROR,
        verified=BeatmapSourceVerification.UNVERIFIED,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _coverage_key(
    window: DirectFeedWindow,
    *,
    from_beatmapset_id: int,
    to_beatmapset_id: int,
) -> tuple[str, str, str, str, str, int, int]:
    """In-memory coverage stateのscope keyを作成する.

    Args:
        window (DirectFeedWindow): coverage scopeを決めるfeed window.
        from_beatmapset_id (int): observed range開始ID.
        to_beatmapset_id (int): observed range終了ID.

    Returns:
        tuple[str, str, str, str, str, int, int]: repository stateで使うscope key.
    """
    return (
        DirectCoverageKind.FEED_WINDOW.value,
        window.source.value,
        window.status_scope.value,
        window.sort_key,
        window.window_key,
        from_beatmapset_id,
        to_beatmapset_id,
    )


def _range_coverage_key(chunk: DirectRangeCrawlChunk) -> tuple[str, str, str, str, str, int, int]:
    """In-memory coverage stateのid range scope keyを作成する.

    Args:
        chunk (DirectRangeCrawlChunk): coverage scopeを決めるid range chunk.

    Returns:
        tuple[str, str, str, str, str, int, int]: repository stateで使うscope key.
    """
    return (
        DirectCoverageKind.ID_RANGE.value,
        chunk.source.value,
        chunk.status_scope.value,
        "id-range",
        f"{chunk.from_beatmapset_id}-{chunk.to_beatmapset_id}",
        chunk.from_beatmapset_id,
        chunk.to_beatmapset_id,
    )

"""osu!direct catalog schedulerの共有budgetと優先度契約を検証するmodule."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from structlog.testing import capture_logs

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    DirectCoverageKind,
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

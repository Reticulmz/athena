"""osu!direct catalog同期の共有upstream budget schedulerを提供するmodule."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, cast

import structlog

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapSet,
    DirectCoverageKind,
    DirectCoverageRecord,
)
from osu_server.shared.ports import DirectCatalogWorkKind

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        BeatmapMetadataSource,
        BeatmapsetSnapshot,
        DirectCoverageStatusScope,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_UPSTREAM_BUDGET_WINDOW_SECONDS = 60
_ID_RANGE_SORT_KEY = "id-range"

_logger = cast(
    "structlog.stdlib.BoundLogger",
    structlog.get_logger(__name__),
)

type DirectCatalogWork = Callable[[], Awaitable[None]]
type TimeFunc = Callable[[], float]


class DirectCatalogScheduleOutcome(StrEnum):
    """DirectCatalogSchedulerがworkへ与えた実行結果を表す.

    Attributes:
        COMPLETED (DirectCatalogScheduleOutcome): budgetを取得してworkが完了した.
        DELAYED (DirectCatalogScheduleOutcome): budget枯渇によりretry可能なdelayになった.
        FAILED (DirectCatalogScheduleOutcome): work実行中に失敗しretry可能な状態を返した.
    """

    COMPLETED = "completed"
    DELAYED = "delayed"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class DirectCatalogScheduleResult:
    """Shared upstream budget schedulerのwork単位結果を表す.

    Attributes:
        work_kind (DirectCatalogWorkKind): schedulerへ渡されたwork種別.
        outcome (DirectCatalogScheduleOutcome): workの実行結果.
        retry_eligible (bool): 呼び出し側が後続retry対象にしてよいか.
        retry_after_seconds (int | None): delay時に次回試行まで待つ推奨秒数.
        failure_reason (str | None): operator向けにsanitize済みの失敗理由.
    """

    work_kind: DirectCatalogWorkKind
    outcome: DirectCatalogScheduleOutcome
    retry_eligible: bool
    retry_after_seconds: int | None = None
    failure_reason: str | None = None


@dataclass(slots=True, frozen=True)
class DirectFeedWindow:
    """Catalog feed同期対象のstatus/sort/window scopeを表す.

    Attributes:
        source (BeatmapMetadataSource): feed metadataの取得source.
        status_scope (DirectCoverageStatusScope): 同期対象のstatus scope.
        sort_key (str): upstream feedのsort識別子.
        window_key (str): page, cursor,またはwindowの識別子.
    """

    source: BeatmapMetadataSource
    status_scope: DirectCoverageStatusScope
    sort_key: str
    window_key: str


@dataclass(slots=True, frozen=True)
class DirectFeedWindowFetchResult:
    """Catalog feed window fetchのmetadata結果を表す.

    Attributes:
        beatmapsets (tuple[BeatmapsetSnapshot, ...]): feedから観測したbeatmapset snapshot列.
        cursor (str | None): 次回取得に使えるupstream cursorまたはpage marker.
    """

    beatmapsets: tuple[BeatmapsetSnapshot, ...]
    cursor: str | None = None


class DirectFeedWindowFetcher(Protocol):
    """Feed windowからbeatmapset metadata snapshotを取得するportを定義する."""

    async def fetch_feed_window(
        self,
        window: DirectFeedWindow,
    ) -> DirectFeedWindowFetchResult:
        """指定されたfeed windowのbeatmapset snapshot列を取得する.

        Args:
            window (DirectFeedWindow): 取得対象のfeed window scope.

        Returns:
            DirectFeedWindowFetchResult: 観測したmetadata snapshotと次cursor.
        """
        ...


@dataclass(slots=True, frozen=True)
class DirectRangeCrawlChunk:
    """Explicit beatmapset id range crawl対象のchunkを表す.

    Attributes:
        source (BeatmapMetadataSource): id range metadataの取得source.
        status_scope (DirectCoverageStatusScope): crawl対象のstatus scope.
        from_beatmapset_id (int): crawl chunk開始beatmapset ID.
        to_beatmapset_id (int): crawl chunk終了beatmapset ID.
    """

    source: BeatmapMetadataSource
    status_scope: DirectCoverageStatusScope
    from_beatmapset_id: int
    to_beatmapset_id: int

    def __post_init__(self) -> None:
        """Crawl chunkの永続coverage用range制約を検証する.

        Returns:
            None: rangeがcoverage recordへ保存可能であることを示す.

        Raises:
            ValueError: rangeが負値または順序不正の場合.
        """
        if self.from_beatmapset_id < 0:
            msg = "from_beatmapset_id must not be negative"
            raise ValueError(msg)
        if self.to_beatmapset_id < self.from_beatmapset_id:
            msg = "to_beatmapset_id must be greater than or equal to from_beatmapset_id"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class DirectRangeCrawlFetchResult:
    """ID range crawl fetchのmetadata結果を表す.

    Attributes:
        beatmapsets (tuple[BeatmapsetSnapshot, ...]): chunkから取得したbeatmapset snapshot列.
    """

    beatmapsets: tuple[BeatmapsetSnapshot, ...]


class DirectRangeCrawlFetcher(Protocol):
    """ID range chunkからbeatmapset metadata snapshotを取得するportを定義する."""

    async def fetch_id_range(
        self,
        chunk: DirectRangeCrawlChunk,
    ) -> DirectRangeCrawlFetchResult:
        """指定されたid range chunkのbeatmapset snapshot列を取得する.

        Args:
            chunk (DirectRangeCrawlChunk): 取得対象のid range chunk.

        Returns:
            DirectRangeCrawlFetchResult: chunkから取得したmetadata snapshot列.
        """
        ...


class DirectCatalogScheduler:
    """Point lookupを優先するosu!direct upstream work scheduler.

    Attributes:
        _request_budget_per_minute (int): 1分間に許可するupstream request数.
        _time_func (TimeFunc): budget window判定用clock.
        _lock (asyncio.Lock): 同時reserveを直列化するlock.
        _window_started_at (float): 現在のbudget window開始時刻.
        _used_budget (int): 現在windowで消費済みのrequest数.
    """

    _request_budget_per_minute: int
    _time_func: TimeFunc
    _lock: asyncio.Lock
    _window_started_at: float
    _used_budget: int

    def __init__(
        self,
        *,
        request_budget_per_minute: int,
        time_func: TimeFunc | None = None,
    ) -> None:
        """Schedulerの共有budgetとclockを初期化する.

        Args:
            request_budget_per_minute (int): 1分間に許可するupstream request数.
            time_func (TimeFunc | None): budget window判定に使う秒単位clock.

        Raises:
            ValueError: request_budget_per_minuteが正でない場合.
        """
        if request_budget_per_minute <= 0:
            msg = "request_budget_per_minute must be positive"
            raise ValueError(msg)
        self._request_budget_per_minute = request_budget_per_minute
        self._time_func = time_func or time.monotonic
        self._lock = asyncio.Lock()
        self._window_started_at = self._time_func()
        self._used_budget = 0

    async def run(
        self,
        work_kind: DirectCatalogWorkKind,
        work: DirectCatalogWork,
    ) -> DirectCatalogScheduleResult:
        """Shared budgetを取得できた場合だけupstream workを実行する.

        Args:
            work_kind (DirectCatalogWorkKind): 実行するworkの種別.
            work (DirectCatalogWork): budget取得後に呼び出す非同期work.

        Returns:
            DirectCatalogScheduleResult: 完了, delay, failureのいずれかを表す結果.
        """
        if _is_catalog_work(work_kind):
            # ponytail: one event-loop tick is enough priority for current worker concurrency.
            await asyncio.sleep(0)

        retry_after_seconds = await self._reserve_budget()
        if retry_after_seconds is not None:
            result = DirectCatalogScheduleResult(
                work_kind=work_kind,
                outcome=DirectCatalogScheduleOutcome.DELAYED,
                retry_eligible=True,
                retry_after_seconds=retry_after_seconds,
            )
            self._log_delay(result)
            return result

        try:
            await work()
        except Exception as exc:
            result = DirectCatalogScheduleResult(
                work_kind=work_kind,
                outcome=DirectCatalogScheduleOutcome.FAILED,
                retry_eligible=True,
                failure_reason=_sanitize_failure_reason(work_kind, exc),
            )
            self._log_failure(result, exc)
            return result

        result = DirectCatalogScheduleResult(
            work_kind=work_kind,
            outcome=DirectCatalogScheduleOutcome.COMPLETED,
            retry_eligible=False,
        )
        self._log_completion(result)
        return result

    async def _reserve_budget(self) -> int | None:
        """現在windowのbudgetを1件予約し,枯渇時はretry秒数を返す.

        Returns:
            int | None: budget枯渇時はretryまでの秒数. 予約できた場合はNone.
        """
        async with self._lock:
            now = self._time_func()
            window_age = now - self._window_started_at
            if window_age >= _UPSTREAM_BUDGET_WINDOW_SECONDS:
                self._window_started_at = now
                self._used_budget = 0
                window_age = 0

            if self._used_budget >= self._request_budget_per_minute:
                retry_after_seconds = math.ceil(_UPSTREAM_BUDGET_WINDOW_SECONDS - window_age)
                return max(1, retry_after_seconds)

            self._used_budget += 1
            return None

    def _log_delay(self, result: DirectCatalogScheduleResult) -> None:
        """Catalog workのdelayとretry stateを構造化logへ出力する.

        Args:
            result (DirectCatalogScheduleResult): delay結果.

        Returns:
            None: log出力のみを行い値を返さない.
        """
        if not _is_catalog_work(result.work_kind):
            return
        _logger.info(
            "osu_direct_catalog_sync_delayed",
            work_kind=result.work_kind.value,
            retry_eligible=result.retry_eligible,
            retry_after_seconds=result.retry_after_seconds,
        )

    def _log_failure(
        self,
        result: DirectCatalogScheduleResult,
        exc: Exception,
    ) -> None:
        """Catalog workの失敗とretry stateを構造化logへ出力する.

        Args:
            result (DirectCatalogScheduleResult): failure結果.
            exc (Exception): sanitize対象の例外.

        Returns:
            None: log出力のみを行い値を返さない.
        """
        if not _is_catalog_work(result.work_kind):
            return
        _logger.warning(
            "osu_direct_catalog_sync_failed",
            work_kind=result.work_kind.value,
            exception_type=type(exc).__name__,
            retry_eligible=result.retry_eligible,
            failure_reason=result.failure_reason,
        )

    def _log_completion(self, result: DirectCatalogScheduleResult) -> None:
        """Catalog workの完了状態を構造化logへ出力する.

        Args:
            result (DirectCatalogScheduleResult): completed結果.

        Returns:
            None: catalog workであれば完了eventを出力して値を返さない.
        """
        if not _is_catalog_work(result.work_kind):
            return
        _logger.info(
            "osu_direct_catalog_sync_completed",
            work_kind=result.work_kind.value,
        )


class DirectFeedSync:
    """Feed windowを同期しmetadata保存後にcoverage stateを記録するuse-case.

    Attributes:
        _unit_of_work_factory (UnitOfWorkFactory): metadataとcoverageを保存するUoW factory.
        _scheduler (DirectCatalogScheduler): upstream budgetと優先度を制御するscheduler.
        _feed_window_fetcher (DirectFeedWindowFetcher): feed window metadata取得port.
    """

    _unit_of_work_factory: UnitOfWorkFactory
    _scheduler: DirectCatalogScheduler
    _feed_window_fetcher: DirectFeedWindowFetcher

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        scheduler: DirectCatalogScheduler,
        feed_window_fetcher: DirectFeedWindowFetcher,
    ) -> None:
        """Feed syncに必要な保存境界, scheduler, fetcherを保持する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): metadataとcoverage用のUoW factory.
            scheduler (DirectCatalogScheduler): shared upstream budget scheduler.
            feed_window_fetcher (DirectFeedWindowFetcher): feed window metadata fetcher.
        """
        self._unit_of_work_factory = unit_of_work_factory
        self._scheduler = scheduler
        self._feed_window_fetcher = feed_window_fetcher

    async def execute(self, window: DirectFeedWindow) -> DirectCatalogScheduleResult:
        """Shared budget下でfeed windowを同期し, coverage結果を保存する.

        Args:
            window (DirectFeedWindow): 同期するfeed window scope.

        Returns:
            DirectCatalogScheduleResult: schedulerによる完了, delay, failure結果.

        Notes:
            成功coverageはmetadata保存と同じUoWで記録する. 失敗coverageはschedulerが返す
            sanitize済みreasonだけを別UoWで記録し, covered扱いにしない.
        """
        observed_range: tuple[int, int] | None = None
        cursor: str | None = None

        async def work() -> None:
            """Schedulerへ渡す実同期workを実行する.

            Returns:
                None: metadataと完了coverageを保存して値を返さずに完了する.
            """
            nonlocal observed_range, cursor

            result = await self._feed_window_fetcher.fetch_feed_window(window)
            observed_range = _observed_beatmapset_id_range(result.beatmapsets)
            cursor = result.cursor

            async with self._unit_of_work_factory() as uow:
                for snapshot in result.beatmapsets:
                    await uow.beatmaps.save_beatmapset_snapshot(_snapshot_to_beatmapset(snapshot))
                completed_at = datetime.now(UTC)
                coverage = _feed_window_coverage_record(
                    window,
                    observed_range=observed_range,
                    cursor=cursor,
                    completed_at=completed_at,
                    failed_at=None,
                    failure_reason=None,
                )
                await uow.beatmaps.record_direct_coverage(coverage)
                await uow.commit()

        result = await self._scheduler.run(DirectCatalogWorkKind.FEED_SYNC, work)
        if result.outcome is DirectCatalogScheduleOutcome.FAILED:
            await self._record_failed_coverage(
                window,
                observed_range=observed_range or (0, 0),
                cursor=cursor,
                failure_reason=result.failure_reason or "catalog work failed",
            )
        return result

    async def _record_failed_coverage(
        self,
        window: DirectFeedWindow,
        *,
        observed_range: tuple[int, int],
        cursor: str | None,
        failure_reason: str,
    ) -> None:
        """Feed window失敗状態をcovered扱いせずに保存する.

        Args:
            window (DirectFeedWindow): 失敗したfeed window scope.
            observed_range (tuple[int, int]): 失敗前に観測できたID範囲. 不明なら(0, 0).
            cursor (str | None): 失敗前に得られたcursor. 不明ならNone.
            failure_reason (str): schedulerがsanitizeしたoperator向け失敗理由.

        Returns:
            None: 失敗coverage recordを保存して完了する.
        """
        coverage = _feed_window_coverage_record(
            window,
            observed_range=observed_range,
            cursor=cursor,
            completed_at=None,
            failed_at=datetime.now(UTC),
            failure_reason=failure_reason,
        )
        async with self._unit_of_work_factory() as uow:
            await uow.beatmaps.record_direct_coverage(coverage)
            await uow.commit()


class DirectRangeCrawl:
    """ID range chunkを同期しmetadata保存後に強いcoverage stateを記録するuse-case.

    Attributes:
        _unit_of_work_factory (UnitOfWorkFactory): metadataとcoverageを保存するUoW factory.
        _scheduler (DirectCatalogScheduler): upstream budgetと優先度を制御するscheduler.
        _range_crawl_fetcher (DirectRangeCrawlFetcher): id range metadata取得port.
    """

    _unit_of_work_factory: UnitOfWorkFactory
    _scheduler: DirectCatalogScheduler
    _range_crawl_fetcher: DirectRangeCrawlFetcher

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        scheduler: DirectCatalogScheduler,
        range_crawl_fetcher: DirectRangeCrawlFetcher,
    ) -> None:
        """Range crawlに必要な保存境界, scheduler, fetcherを保持する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): metadataとcoverage用のUoW factory.
            scheduler (DirectCatalogScheduler): shared upstream budget scheduler.
            range_crawl_fetcher (DirectRangeCrawlFetcher): id range metadata fetcher.
        """
        self._unit_of_work_factory = unit_of_work_factory
        self._scheduler = scheduler
        self._range_crawl_fetcher = range_crawl_fetcher

    async def execute(self, chunk: DirectRangeCrawlChunk) -> DirectCatalogScheduleResult:
        """Shared budget下でid range chunkを同期し, coverage結果を保存する.

        Args:
            chunk (DirectRangeCrawlChunk): 同期するid range chunk.

        Returns:
            DirectCatalogScheduleResult: schedulerによる完了, delay, failure結果.

        Notes:
            成功coverageはmetadata保存と同じUoWで記録する. 失敗coverageはschedulerが返す
            sanitize済みreasonだけを別UoWで記録し, covered扱いにしない.
        """

        async def work() -> None:
            """Schedulerへ渡す実同期workを実行する.

            Returns:
                None: metadataと完了coverageを保存して値を返さずに完了する.
            """
            result = await self._range_crawl_fetcher.fetch_id_range(chunk)

            async with self._unit_of_work_factory() as uow:
                for snapshot in result.beatmapsets:
                    await uow.beatmaps.save_beatmapset_snapshot(_snapshot_to_beatmapset(snapshot))
                coverage = _id_range_coverage_record(
                    chunk,
                    completed_at=datetime.now(UTC),
                    failed_at=None,
                    failure_reason=None,
                )
                await uow.beatmaps.record_direct_coverage(coverage)
                await uow.commit()

        result = await self._scheduler.run(DirectCatalogWorkKind.ID_RANGE_CRAWL, work)
        if result.outcome is DirectCatalogScheduleOutcome.FAILED:
            await self._record_failed_coverage(
                chunk,
                failure_reason=result.failure_reason or "catalog work failed",
            )
        return result

    async def _record_failed_coverage(
        self,
        chunk: DirectRangeCrawlChunk,
        *,
        failure_reason: str,
    ) -> None:
        """ID range chunk失敗状態をcovered扱いせずに保存する.

        Args:
            chunk (DirectRangeCrawlChunk): 失敗したid range chunk.
            failure_reason (str): schedulerがsanitizeしたoperator向け失敗理由.

        Returns:
            None: 失敗coverage recordを保存して完了する.
        """
        coverage = _id_range_coverage_record(
            chunk,
            completed_at=None,
            failed_at=datetime.now(UTC),
            failure_reason=failure_reason,
        )
        async with self._unit_of_work_factory() as uow:
            await uow.beatmaps.record_direct_coverage(coverage)
            await uow.commit()


class RecordDirectSearchCoverageUseCase:
    """検索時に観測したosu!direct coverageを保存するcommand use-case.

    Attributes:
        _unit_of_work_factory (UnitOfWorkFactory): coverage recordを書き込むUoW factory.
    """

    _unit_of_work_factory: UnitOfWorkFactory

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        """Coverage保存用UoW factoryを保持する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): coverage recordを書き込むfactory.
        """
        self._unit_of_work_factory = unit_of_work_factory

    async def execute(self, record: DirectCoverageRecord) -> None:
        """Coverage recordを保存する.

        Args:
            record (DirectCoverageRecord): 検索またはcatalog jobが観測したcoverage record.

        Returns:
            None: coverage recordをcommitして値を返さず完了する.
        """
        async with self._unit_of_work_factory() as uow:
            await uow.beatmaps.record_direct_coverage(record)
            await uow.commit()


def _is_catalog_work(work_kind: DirectCatalogWorkKind) -> bool:
    """Work種別がbackground catalog workか判定する.

    Args:
        work_kind (DirectCatalogWorkKind): 判定するwork種別.

    Returns:
        bool: feed syncまたはid range crawlならTrue.
    """
    return work_kind is not DirectCatalogWorkKind.POINT_LOOKUP


def _sanitize_failure_reason(work_kind: DirectCatalogWorkKind, exc: Exception) -> str:
    """例外をoperator向けの固定messageへ変換する.

    Args:
        work_kind (DirectCatalogWorkKind): 失敗したwork種別.
        exc (Exception): workから送出された例外.

    Returns:
        str: credentialやupstream bodyを含まない失敗理由.
    """
    category = "catalog" if _is_catalog_work(work_kind) else "point lookup"
    return f"{type(exc).__name__}: {category} work failed"


def _observed_beatmapset_id_range(
    beatmapsets: tuple[BeatmapsetSnapshot, ...],
) -> tuple[int, int]:
    """Feed結果から観測beatmapset ID範囲を求める.

    Args:
        beatmapsets (tuple[BeatmapsetSnapshot, ...]): feed windowで観測したsnapshot列.

    Returns:
        tuple[int, int]: 観測IDの最小値と最大値. 空feedでは(0, 0).
    """
    if not beatmapsets:
        return (0, 0)
    beatmapset_ids = [snapshot.beatmapset_id for snapshot in beatmapsets]
    return (min(beatmapset_ids), max(beatmapset_ids))


def _feed_window_coverage_record(
    window: DirectFeedWindow,
    *,
    observed_range: tuple[int, int],
    cursor: str | None,
    completed_at: datetime | None,
    failed_at: datetime | None,
    failure_reason: str | None,
) -> DirectCoverageRecord:
    """Feed window scopeと実行結果からcoverage recordを作る.

    Args:
        window (DirectFeedWindow): coverage scopeを定義するfeed window.
        observed_range (tuple[int, int]): 観測したbeatmapset ID範囲.
        cursor (str | None): upstream cursorまたはpage marker.
        completed_at (datetime | None): 成功完了時刻.
        failed_at (datetime | None): 失敗時刻.
        failure_reason (str | None): sanitized failure reason.

    Returns:
        DirectCoverageRecord: 保存するfeed window coverage state.
    """
    from_beatmapset_id, to_beatmapset_id = observed_range
    return DirectCoverageRecord(
        coverage_kind=DirectCoverageKind.FEED_WINDOW,
        source=window.source,
        status_scope=window.status_scope,
        sort_key=window.sort_key,
        window_key=window.window_key,
        from_beatmapset_id=from_beatmapset_id,
        to_beatmapset_id=to_beatmapset_id,
        cursor=cursor,
        completed_at=completed_at,
        failed_at=failed_at,
        failure_reason=failure_reason,
    )


def _id_range_coverage_record(
    chunk: DirectRangeCrawlChunk,
    *,
    completed_at: datetime | None,
    failed_at: datetime | None,
    failure_reason: str | None,
) -> DirectCoverageRecord:
    """ID range chunk scopeと実行結果からcoverage recordを作る.

    Args:
        chunk (DirectRangeCrawlChunk): coverage scopeを定義するid range chunk.
        completed_at (datetime | None): 成功完了時刻.
        failed_at (datetime | None): 失敗時刻.
        failure_reason (str | None): sanitized failure reason.

    Returns:
        DirectCoverageRecord: 保存するid range coverage state.
    """
    return DirectCoverageRecord(
        coverage_kind=DirectCoverageKind.ID_RANGE,
        source=chunk.source,
        status_scope=chunk.status_scope,
        sort_key=_ID_RANGE_SORT_KEY,
        window_key=f"{chunk.from_beatmapset_id}-{chunk.to_beatmapset_id}",
        from_beatmapset_id=chunk.from_beatmapset_id,
        to_beatmapset_id=chunk.to_beatmapset_id,
        cursor=None,
        completed_at=completed_at,
        failed_at=failed_at,
        failure_reason=failure_reason,
    )


def _snapshot_to_beatmapset(snapshot: BeatmapsetSnapshot) -> BeatmapSet:
    """Provider snapshotを永続化用BeatmapSetへ変換する.

    Args:
        snapshot (BeatmapsetSnapshot): feed fetcherから得たbeatmapset metadata.

    Returns:
        BeatmapSet: command repositoryへ保存するmetadata aggregate.
    """
    beatmaps = tuple(
        Beatmap(
            id=beatmap.beatmap_id,
            beatmapset_id=beatmap.beatmapset_id,
            checksum_md5=beatmap.checksum_md5,
            mode=beatmap.mode,
            version=beatmap.version,
            total_length=beatmap.total_length,
            hit_length=beatmap.hit_length,
            max_combo=beatmap.max_combo,
            bpm=beatmap.bpm,
            cs=beatmap.cs,
            od=beatmap.od,
            ar=beatmap.ar,
            hp=beatmap.hp,
            difficulty_rating=beatmap.difficulty_rating,
            official_status=beatmap.official_status,
            official_status_source=beatmap.official_status_source,
            official_status_verified=beatmap.official_status_verified,
            local_status_override=beatmap.local_status_override,
            metadata_fetch_state=BeatmapFetchState.FRESH,
            file_state=BeatmapFileState.MISSING,
            file_attachment=None,
            last_fetched_at=beatmap.last_fetched_at,
            next_refresh_at=beatmap.next_refresh_at,
            official_last_updated_at=beatmap.official_last_updated_at,
        )
        for beatmap in snapshot.beatmaps
    )
    return BeatmapSet(
        id=snapshot.beatmapset_id,
        artist=snapshot.artist,
        title=snapshot.title,
        creator=snapshot.creator,
        artist_unicode=snapshot.artist_unicode,
        title_unicode=snapshot.title_unicode,
        official_status=snapshot.official_status,
        official_status_source=snapshot.official_status_source,
        official_status_verified=snapshot.official_status_verified,
        beatmaps=beatmaps,
        last_fetched_at=snapshot.last_fetched_at,
        next_refresh_at=snapshot.next_refresh_at,
        official_submitted_at=snapshot.official_submitted_at,
        official_ranked_at=snapshot.official_ranked_at,
        official_last_updated_at=snapshot.official_last_updated_at,
        source_text=snapshot.source_text,
        tags=snapshot.tags,
    )


__all__ = [
    "DirectCatalogScheduleOutcome",
    "DirectCatalogScheduleResult",
    "DirectCatalogScheduler",
    "DirectCatalogWork",
    "DirectCatalogWorkKind",
    "DirectFeedSync",
    "DirectFeedWindow",
    "DirectFeedWindowFetchResult",
    "DirectFeedWindowFetcher",
    "DirectRangeCrawl",
    "DirectRangeCrawlChunk",
    "DirectRangeCrawlFetchResult",
    "DirectRangeCrawlFetcher",
]
